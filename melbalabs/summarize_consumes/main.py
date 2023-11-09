import argparse
import json
import collections
import datetime
import io
import os
import re
import sys
import time
import webbrowser
import functools
import logging
from datetime import datetime as dt

import requests
import humanize
import lark


from melbalabs.summarize_consumes import grammar


LarkError = lark.LarkError

class App:
    pass


@functools.cache
def create_parser(grammar: str, debug):
    return lark.Lark(
        grammar,
        parser='lalr',
        debug=debug,
        # ambiguity='explicit',  # not in lalr
        strict=True,
    )


def create_app(expert_log_unparsed_lines):

    app = App()

    lark_debug = False
    if expert_log_unparsed_lines:
        lark.logger.setLevel(logging.DEBUG)
        lark_debug = True

    app.parser = create_parser(grammar=grammar.grammar, debug=lark_debug)


    if expert_log_unparsed_lines:
        app.unparsed_logger = UnparsedLogger(filename='unparsed.txt')
    else:
        app.unparsed_logger = NullLogger(filename='unparsed.txt')


    # player - consumable - count
    app.player = collections.defaultdict(lambda: collections.defaultdict(int))

    # player - consumable - unix_timestamp
    app.last_hit_cache = collections.defaultdict(lambda: collections.defaultdict(float))

    # player - set of reasons this is considered a player
    app.player_detect = collections.defaultdict(set)

    # pet -> owner
    app.pet_detect = dict()

    # name -> death count
    app.death_count = collections.defaultdict(int)

    app.hits_consumable = HitsConsumable(player=app.player, last_hit_cache=app.last_hit_cache)

    app.pricedb = PriceDB('prices.json')
    app.print_consumables = PrintConsumables(player=app.player, pricedb=app.pricedb, death_count=app.death_count)

    # bwl
    app.nef_corrupted_healing = NefCorruptedHealing()
    # aq
    app.viscidus = Viscidus()
    app.huhuran = Huhuran()
    app.cthun_chain = BeamChain(logname="C'Thun Chain Log (2+)", beamname="Eye of C'Thun 's Eye Beam", chainsize=2)
    # naxx
    app.gluth = Gluth()
    app.fourhm_chain = BeamChain(logname="4HM Zeliek Chain Log (4+)", beamname="Sir Zeliek 's Holy Wrath", chainsize=4)
    app.kt_frostblast = KTFrostblast()
    app.kt_frostbolt = KTFrostbolt()
    app.kt_shadowfissure = KTShadowfissure()
    app.kt_guardian = KTGuardian()

    app.techinfo = Techinfo()

    return app



def parse_ts2unixtime(timestamp):
    month, day, hour, minute, sec, ms = timestamp.children
    month = int(month)
    day = int(day)
    hour = int(hour)
    minute = int(minute)
    sec = int(sec)
    ms = int(ms)
    timestamp = dt(year=CURRENT_YEAR, month=month, day=day, hour=hour, minute=minute, second=sec, tzinfo=datetime.timezone.utc)
    unixtime = timestamp.timestamp()  # seconds
    return unixtime


class HitsConsumable:


    COOLDOWNS = {
        'Dragonbreath Chili': 10 * 60,
        'Goblin Sapper Charge': 5 * 60,
    }

    def __init__(self, player, last_hit_cache):
        self.player = player
        self.last_hit_cache = last_hit_cache

    def update(self, name, consumable, timestamp):
        cooldown = self.COOLDOWNS[consumable]
        unixtime =  parse_ts2unixtime(timestamp)
        delta = unixtime - self.last_hit_cache[name][consumable]
        if delta >= cooldown:
            self.player[name][consumable] += 1
            self.last_hit_cache[name][consumable] = unixtime
        elif delta < 0:
            # probably a new year, will ignore for now
            raise RuntimeError('fixme')




RENAME_CONSUMABLE = {
    'Supreme Power': 'Flask of Supreme Power',
    'Distilled Wisdom': 'Flask of Distilled Wisdom',
    'Rage of Ages': 'Rage of Ages (ROIDS)',
    'Health II': 'Elixir of Fortitude',
    'Fury of the Bogling': 'Bogling Root',
    'Elixir of the Sages': '??? Elixir of the Sages ???',
    'Shadow Power': 'Elixir of Shadow Power',
    'Greater Firepower': 'Elixir of Greater Firepower',
    'Fire Power': 'Elixir of Firepower',
    'Greater Agility': 'Elixir of Greater Agility',
    'Spirit of the Boar': 'Lung Juice Cocktail',
    'Greater Armor': 'Elixir of Superior Defense',
    'Mana Regeneration': 'Mana Regeneration (food or mageblood)',
    'Free Action': 'Free Action Potion',
    'Frost Power': 'Elixir of Frost Power',
    'Nature Protection ': 'Nature Protection',
    'Shadow Protection ': 'Shadow Protection',
    'Holy Protection ': 'Holy Protection',
    '100 energy': 'Thistle Tea',
    'Sharpen Weapon - Critical': 'Elemental Sharpening Stone',
    'Consecrated Weapon': 'Consecrated Sharpening Stone',
    'Sharpen Blade V': 'Dense Sharpening Stone',
    'Enhance Blunt Weapon V': 'Dense Weighstone',
    'Cure Ailments': 'Jungle Remedy',
    'Stoneshield': '??? Lesser Stoneshield Potion ???',
    'Restoration': 'Restorative Potion',
    'Enlarge': 'Elixir of Giant Growth',
    'Greater Intellect': 'Elixir of Greater Intellect',
    'Infallible Mind': 'Infallible Mind (Cerebral Cortex Compound)',
    'Crystal Protection': 'Crystal Protection (Crystal Basilisk Spine)',
}

CONSUMABLE_COMPONENTS = {
    'Rage of Ages (ROIDS)': [
        ('Scorpok Pincer', 1),
        ('Blasted Boar Lung', 2),
        ('Snickerfang Jowl', 3),
    ],
    'Strike of the Scorpok': [
        ('Blasted Boar Lung', 1),
        ('Vulture Gizzard', 2),
        ('Scorpok Pincer', 3),
    ],
    'Lung Juice Cocktail': [
        ('Basilisk Brain', 1),
        ('Scorpok Pincer', 2),
        ('Blasted Boar Lung', 3),
    ],
    'Infallible Mind (Cerebral Cortex Compound)': [
        ('Basilisk Brain', 10),
        ('Vulture Gizzard', 2),
    ],
    "Brilliant Mana Oil": [
        ('Purple Lotus', 3),
        ('Large Brilliant Shard', 2),
    ],
    "Spirit of Zanza": [
        ('Zulian Coin', 3),
    ],
    "Swiftness of Zanza": [
        ('Zulian Coin', 3),
    ],
}

NAME2ITEMID = {
    "Flask of the Titans": 13510,
    "Flask of Supreme Power": 13512,
    'Flask of Distilled Wisdom': 13511,
    'Elixir of Fortitude': 3825,
    'Bogling Root': 5206,
    '??? Elixir of the Sages ???': 13447,
    'Elixir of Shadow Power': 9264,
    'Elixir of Greater Firepower': 21546,
    'Elixir of Firepower': 6373,
    'Elixir of Greater Agility': 9187,
    'Elixir of Superior Defense': 13445,
    'Free Action Potion': 5634,
    'Elixir of Frost Power': 17708,
    'Greater Arcane Elixir': 13454,
    'Thistle Tea': 7676,
    'Elemental Sharpening Stone': 18262,
    'Elixir of the Mongoose': 13452,
    'Winterfall Firewater': 12820,
    'Greater Stoneshield': 13455,
    'Elixir of Greater Agility': 9187,
    'Scorpok Pincer': 8393,
    'Blasted Boar Lung': 8392,
    'Snickerfang Jowl': 8391,
    'Basilisk Brain': 8394,
    'Vulture Gizzard': 8396,
    'Large Brilliant Shard': 14344,
    'Purple Lotus': 8831,
    'Mana Potion - Greater': 6149,
    'Mana Potion - Superior': 13443,
    'Mana Potion - Major': 13444,
    'Restorative Potion': 9030,
    'Healing Potion - Major': 13446,
    'Elixir of the Giants': 9206,
    'Zulian Coin': 19698,
    "Rumsey Rum Black Label": 21151,
    'Consecrated Sharpening Stone': 23122,
    'Invulnerability': 3387,
    'Dragonbreath Chili': 12217,
    'Dreamtonic': 61423,
    'Goblin Sapper Charge': 10646,
    "Medivh's Merlot": 61174,
    'Shadow Protection': 13459,
    'Dreamshard Elixir': 61224,
    'Lesser Mana Oil': 20747,
    'Brilliant Mana Oil': 20748,
    'Mighty Rage Potion': 13442,
    'Dense Dynamite': 18641,
    'Brilliant Wizard Oil': 20749,
    'Wizard Oil': 20750,
    'Blessed Wizard Oil': 23123,
    'Thorium Grenade': 15993,
    'Potion of Quickness': 61181,
    "Medivh's Merlot Blue Label": 61175,
    'Elixir of Greater Nature Power': 50237,
    'Elixir of Greater Intellect': 9179,
    'Rejuvenation Potion - Major': 18253,
}
ITEMID2NAME = { value: key for key, value in NAME2ITEMID.items() }

CONSUMABLE_CHARGES = {
    "Brilliant Mana Oil" : 5,
    "Lesser Mana Oil" : 5,
    "Brilliant Wizard Oil" : 5,
    "Wizard Oil" : 5,
}

RAGE_CONSUMABLE = {
    "Mighty Rage",
    "Great Rage",
    "Rage",
}



BEGINS_TO_CAST_CONSUMABLE = {
    "Brilliant Mana Oil",
    "Lesser Mana Oil",
    "Brilliant Wizard Oil",
    "Blessed Wizard Oil",
    "Wizard Oil",
    "Frost Oil",
    "Shadow Oil",
    "Dense Dynamite",
    "Solid Dynamite",
    "Sharpen Weapon - Critical",
    "Consecrated Weapon",
    "Iron Grenade",
    "Thorium Grenade",
    "Kreeg's Stout Beatdown",
    "Fire-toasted Bun",
    "Sharpen Blade V",
    "Enhance Blunt Weapon V",
    "Crystal Force",
}

CASTS_CONSUMABLE = {
    "Powerful Anti-Venom",
    "Strong Anti-Venom",
    "Cure Ailments",
    "Advanced Target Dummy",
}


GAINS_CONSUMABLE = {
    "Greater Arcane Elixir",
    "Arcane Elixir",
    "Elixir of the Mongoose",
    "Elixir of the Giants",
    "Elixir of the Sages",
    "Elixir of Resistance",
    "Elixir of Greater Nature Power",
    "Flask of the Titans",
    "Supreme Power",
    "Distilled Wisdom",
    "Spirit of Zanza",
    "Swiftness of Zanza",
    "Sheen of Zanza",
    "Rage of Ages",
    "Invulnerability",
    "Potion of Quickness",
    "Noggenfogger Elixir",
    "Shadow Power",
    "Stoneshield",
    "Health II",
    "Rumsey Rum Black Label",
    "Rumsey Rum",
    "Fury of the Bogling",
    "Winterfall Firewater",
    "Greater Agility",
    "Greater Firepower",
    "Greater Armor",
    "Greater Stoneshield",
    "Fire Power",
    "Strike of the Scorpok",
    "Spirit of the Boar",
    "Free Action",
    "Blessed Sunfruit",
    "Gordok Green Grog",
    "Frost Power",
    "Gift of Arthas",
    "100 Energy",  # Restore Energy aka Thistle Tea
    "Restoration",
    "Crystal Ward",
    "Infallible Mind",
    "Crystal Protection",
    "Dreamtonic",
    "Dreamshard Elixir",
    "Medivh's Merlot",
    "Medivh's Merlot Blue Label",
    # ambiguous
    "Increased Stamina",
    "Increased Intellect",
    "Mana Regeneration",
    "Regeneration",
    "Agility",  # pots or scrolls
    "Strength",
    "Stamina",
    "Enlarge",
    "Greater Intellect",
    "Greater Armor",
    ## "Armor",  # same as a spell?
    # protections
    "Fire Protection",
    "Frost Protection",
    "Arcane Protection",
    # extra space here because there's a spell version with no space, which shouldn't match
    "Nature Protection ",
    "Shadow Protection ",
    "Holy Protection ",
}


MANARUNE_CONSUMABLE = {
    "Demonic Rune",
    "Dark Rune",
}


INTERRUPT_SPELLS = {
    'Kick',
    'Pummel',
    'Shield Bash',
    'Earth Shock',
}

BUFF_SPELL = {
    "Greater Blessing of Wisdom",
    "Greater Blessing of Salvation",
    "Greater Blessing of Light",
    "Greater Blessing of Kings",
    "Greater Blessing of Might",
    "Prayer of Spirit",
    "Prayer of Fortitude",
    "Prayer of Shadow Protection",
}



def healpot_lookup(amount):
    # bigger ranges for rounding errors
    if 1049 <= amount <= 1751:
        return 'Healing Potion - Major'
    if 699 <= amount <= 901:
        return 'Healing Potion - Superior'
    if 454 <= amount <= 586:
        return 'Healing Potion - Greater'
    if 139 <= amount <= 181:
        return 'Healing Potion - Lesser'
    if 69 <= amount <= 91:
        return 'Healing Potion - Minor'
    return 'Healing Potion - unknown'

def manapot_lookup(mana):
    consumable = 'Restore Mana (mana potion?)'
    if 1350 <= mana <= 2250:
        consumable = 'Mana Potion - Major'
    elif 900 <= mana <= 1500:
        consumable = 'Mana Potion - Superior'
    elif 700 <= mana <= 900:
        consumable = 'Mana Potion - Greater'
    elif 455 <= mana <= 585:
        consumable = 'Mana Potion - 455 to 585'
    elif 280 <= mana <= 360:
        consumable = 'Mana Potion - Lesser'
    elif 140 <= mana <= 180:
        consumable = 'Mana Potion - Minor'
    return consumable







class LogParser:
    # simple slow parser for individual lines with no context

    def __init__(self, logname, needles):
        self.log = []
        self.logname = logname
        self.needles = needles

    def parse(self, line):
        for needle in self.needles:
            match = re.search(needle, line)
            if match:
                self.log.append(line)
                return 1

    def print(self, output):
        if not self.log: return

        print(f"\n\n{self.logname}", file=output)
        for line in self.log:
            print('  ', line, end='', file=output)




def print_collected_log(section_name, log_list, output):
    if not log_list: return
    print(f"\n\n{section_name}", file=output)
    for line in log_list:
        print('  ', line, end='', file=output)
    return



class KTFrostbolt:
    def __init__(self):
        self.logname = 'KT Frostbolt Log'
        self.log = []
    def begins_to_cast(self, line):
        self.log.append('\n')
        self.log.append(line)
    def add(self, line):
        self.log.append(line)
    def parry(self, line):
        line = "*** honorable mention *** " + line
        self.log.append(line)
    def print(self, output):
        print_collected_log(self.logname, self.log, output)

class KTFrostblast:
    def __init__(self):
        self.logname = 'KT Frost Blast Log'
        self.log = []
    def add(self, line):
        self.log.append(line)
    def print(self, output):
        print_collected_log(self.logname, self.log, output)

class KTShadowfissure:
    def __init__(self):
        self.logname = 'KT Shadow Fissure Log'
        self.log = []
    def add(self, line):
        self.log.append(line)
    def print(self, output):
        print_collected_log(self.logname, self.log, output)

class KTGuardian:
    def __init__(self):
        self.logname = 'KT Guardian of Icecrown Log'
        self.log = []
    def add(self, line):
        self.log.append(line)
    def print(self, output):
        print_collected_log(self.logname, self.log, output)

class Viscidus:
    def __init__(self):
        self.logname = 'Viscidus Frost Hits Log'
        # player - frost spell - count
        self.counts = collections.defaultdict(lambda: collections.defaultdict(int))
        self.totals = collections.defaultdict(int)
        self._found = False
    def add(self, player, spell):
        self.counts[player][spell] += 1
        self.totals[player] += 1
    def found(self):
        self._found = True
    def print(self, output):
        if not self._found: return
        print(f"\n\n{self.logname}", file=output)
        players = [(total, player) for player, total in self.totals.items()]
        players.sort(reverse=True)
        print("  ", "Total hits", sum(total for total, player in players), file=output)
        print(file=output)
        for total, player in players:
            print("  ", player, total, file=output)
            spells = [(total, spell) for spell, total in self.counts[player].items()]
            spells.sort(reverse=True)
            for total, spell in spells:
                print("  ", "  ", spell, total, file=output)

class Huhuran:
    def __init__(self):
        self.logname = 'Princess Huhuran Log'
        self.log = []
    def add(self, line):
        self.log.append(line)
    def print(self, output):
        print_collected_log(self.logname, self.log, output)

class NefCorruptedHealing:
    def __init__(self):
        self.logname = 'Nefarian Priest Corrupted Healing'
        self.log = []
    def add(self, line):
        self.log.append(line)
    def print(self, output):
        print_collected_log(self.logname, self.log, output)

class Gluth:
    def __init__(self):
        self.logname = 'Gluth Log'
        self.log = []
    def add(self, line):
        self.log.append(line)
    def print(self, output):
        print_collected_log(self.logname, self.log, output)


class BeamChain:
    def __init__(self, logname, beamname, chainsize):
        self.log = []  # for debugging/testing

        self.current_batch = []
        self.batches = []

        self.last_ts = 0
        self.logname = logname
        self.beamname = beamname
        self.chainsize = chainsize  # report chains bigger than this


    def add(self, timestamp, line):
        self.log.append(line)

        cooldown = 2
        unixtime = parse_ts2unixtime(timestamp)
        delta = unixtime - self.last_ts
        if delta >= cooldown:
            self.commitbatch()
            self.last_ts = unixtime

        self.current_batch.append(line)

    def commitbatch(self):
        if self.current_batch:
            self.batches.append(self.current_batch)
            self.current_batch = []

    def print(self, output):
        if not self.log: return

        self.commitbatch()

        found_batch = 0
        print(f"\n\n{self.logname}", file=output)

        for batch in self.batches:
            if len(batch) < self.chainsize: continue

            found_batch = 1

            print(file=output)
            for line in batch:
                print('  ', line, end='', file=output)

        if not found_batch:
            print('  ', f'<no chains of {self.chainsize} found. well done>', end='', file=output)



class Techinfo:
    def __init__(self):
        self.time_start = time.time()
        self.logsize = 0
        self.linecount = 0
        self.skiplinecount = 0

    def get_file_size(self, filename):
        self.logsize = os.path.getsize(filename)

    def get_line_count(self, count):
        self.linecount = count

    def get_skipped_line_count(self, count):
        self.skiplinecount = count

    def print(self, output):
        time_end = time.time()
        time_delta = time_end - self.time_start
        print("\n\nTech", file=output)
        print('  ', f'log size {humanize.naturalsize(self.logsize)}', file=output)
        print('  ', f'log lines {self.linecount}', file=output)
        print('  ', f'skipped log lines {self.skiplinecount} ({(self.skiplinecount / self.linecount) * 100:.2f}%)', file=output)
        print('  ', f'processed in {time_delta:.2f} seconds. {self.linecount / time_delta:.2f} log lines/sec', file=output)



class UnparsedLogger:
    def __init__(self, filename):
        self.filename = filename
        self.buffer = io.StringIO()

    def log(self, line):
        print(line, end='', file=self.buffer)

    def flush(self):
        with open(self.filename, 'wb') as f:
            f.write(self.buffer.getvalue().encode('utf8'))

class NullLogger:
    def __init__(self, filename):
        pass
    def log(self, line):
        pass
    def flush(self):
        pass

class PriceDB:
    def __init__(self, filename):
        self.data = dict()
        self.last_update = 0

        if not os.path.exists(filename):
            logging.warning(f'price data not available. {filename} not found')
            return
        with open(filename) as f:
            incoming = json.load(f)
            self.last_update = incoming['last_update']
            for key, val in incoming['data'].items():
                key = int(key)
                self.data[key] = val

    def lookup(self, itemid):
        return self.data.get(itemid)



CURRENT_YEAR = datetime.datetime.now().year



def parse_line(app, line):
    """
    returns True when a match is found, so we can stop trying different parsers
    """
    try:

        tree = app.parser.parse(line)
        timestamp = tree.children[0]
        subtree = tree.children[1]

        # inline some parsing to reduce funcalls
        # for same reason not using visitors to traverse the parse tree
        if subtree.data == 'gains_line':
            name = subtree.children[0].value
            spellname = subtree.children[1].value

            if spellname in GAINS_CONSUMABLE:
                consumable = spellname
                if consumable in RENAME_CONSUMABLE:
                    consumable = RENAME_CONSUMABLE[consumable]
                app.player[name][consumable] += 1

            if spellname in BUFF_SPELL:
                app.player_detect[name].add('buff: ' + spellname)

            if name == 'Princess Huhuran' and spellname in {'Frenzy', 'Berserk'}:
                app.huhuran.add(line)
            if name == 'Gluth' and spellname == 'Frenzy':
                app.gluth.add(line)

            return True
        elif subtree.data == 'gains_rage_line':
            name = subtree.children[0].value
            consumable = subtree.children[3].value
            if consumable in RAGE_CONSUMABLE:
                consumable += ' Potion'
                app.player[name][consumable] += 1
            return True
        elif subtree.data == 'gains_energy_line':
            return True
        elif subtree.data == 'gains_health_line':
            return True
        elif subtree.data == 'dies_line':
            name = subtree.children[0].value
            app.death_count[name] += 1

            if name == 'Princess Huhuran':
                app.huhuran.add(line)
            if name == 'Gluth':
                app.gluth.add(line)

            return True
        elif subtree.data == 'heals_line':
            name = subtree.children[0].value
            spellname = subtree.children[1].value
            if spellname == 'Tea with Sugar':
                app.player[name]['Tea with Sugar'] += 1
            elif spellname == 'Healing Potion':
                is_crit = subtree.children[2].type == 'HEAL_CRIT'
                amount = int(subtree.children[-1].value)
                if is_crit:
                    amount = amount / 1.5
                consumable = healpot_lookup(amount)
                app.player[name][consumable] += 1
            elif spellname == 'Rejuvenation Potion':
                amount = int(subtree.children[-1].value)
                if amount > 500:
                    app.player[name]['Rejuvenation Potion - Major'] += 1
                else:
                    app.player[name]['Rejuvenation Potion - Minor'] += 1

            return True

        elif subtree.data == 'gains_mana_line':
            name = subtree.children[0].value
            consumable = subtree.children[-1].value
            if consumable in MANARUNE_CONSUMABLE:
                app.player[name][consumable] += 1
            elif consumable == 'Restore Mana':
                mana = int(subtree.children[1].value)
                consumable = manapot_lookup(mana)
                app.player[name][consumable] += 1

            return True
        elif subtree.data == 'begins_to_cast_line':
            name = subtree.children[0].value
            spellname = subtree.children[-1].value

            if spellname in BEGINS_TO_CAST_CONSUMABLE:
                consumable = spellname
                if consumable in RENAME_CONSUMABLE:
                    consumable = RENAME_CONSUMABLE[consumable]
                app.player[name][consumable] += 1

            if name == "Kel'Thuzad" and spellname == 'Frostbolt':
                app.kt_frostbolt.begins_to_cast(line)

            return True
        elif subtree.data == 'casts_line':
            name = subtree.children[0].value
            spellname = subtree.children[1].value

            if spellname in CASTS_CONSUMABLE:
                consumable = spellname
                if consumable in RENAME_CONSUMABLE:
                    consumable = RENAME_CONSUMABLE[consumable]
                app.player[name][consumable] += 1

            if name == "Kel'Thuzad" and spellname == "Shadow Fissure":
                app.kt_shadowfissure.add(line)

            if spellname == 'Death by Peasant':
                app.huhuran.add(line)

            if len(subtree.children) == 3:
                targetname = subtree.children[2].value

                if spellname == 'Tranquilizing Shot' and targetname == 'Princess Huhuran':
                    app.huhuran.add(line)
                if spellname == 'Tranquilizing Shot' and targetname == 'Gluth':
                    app.gluth.add(line)

            return True
        elif subtree.data == 'combatant_info_line':
            return True
        elif subtree.data == 'consolidated_line':
            for entry in subtree.children:
                if entry.data == 'consolidated_pet':
                    name = entry.children[0].value
                    petname = entry.children[1].value
                    app.pet_detect[petname] = name
                    app.player_detect[name].add('pet: ' + petname)
                else:
                    # parse but ignore the other consolidated entries
                    pass
            return True
        elif subtree.data == 'hits_ability_line':

            name = subtree.children[0].value
            spellname = subtree.children[1].value
            targetname = subtree.children[2].value

            if spellname in app.hits_consumable.COOLDOWNS:
                app.hits_consumable.update(name, spellname, timestamp)

            if targetname == 'Viscidus':
                app.viscidus.found()
                spell_damage_type = subtree.children[4]
                if spell_damage_type and spell_damage_type.children[0].value == 'Frost':
                    app.viscidus.add(name, spellname)

            if name == "Eye of C'Thun" and spellname == "Eye Beam":
                app.cthun_chain.add(timestamp, line)

            if name == 'Gluth' and spellname == 'Decimate':
                app.gluth.add(line)

            if name == "Sir Zeliek" and spellname == "Holy Wrath":
                app.fourhm_chain.add(timestamp, line)

            if spellname in INTERRUPT_SPELLS and targetname == "Kel'Thuzad":
                app.kt_frostbolt.add(line)

            if name == "Kel'Thuzad" and spellname == "Frostbolt" and int(subtree.children[3].value) >= 4000:
                app.kt_frostbolt.add(line)

            if name == "Kel'Thuzad" and spellname == "Frost Blast":
                app.kt_frostblast.add(line)

            if name == "Shadow Fissure" and spellname == "Void Blast":
                app.kt_shadowfissure.add(line)

            return True
        elif subtree.data == "hits_autoattack_line":
            name = subtree.children[0].value
            if name == 'Guardian of Icecrown':
                app.kt_guardian.add(line)
            return True
        elif subtree.data == 'parry_ability_line':
            name = subtree.children[0].value
            spellname = subtree.children[1].value
            targetname = subtree.children[2].value

            if spellname in INTERRUPT_SPELLS and targetname == "Kel'Thuzad":
                app.kt_frostbolt.parry(line)

            return True
        elif subtree.data == 'parry_line':
            return True

        elif subtree.data == 'resist_line':
            name = subtree.children[0].value
            spellname = subtree.children[1].value
            targetname = subtree.children[2].value


            if spellname in app.hits_consumable.COOLDOWNS:
                app.hits_consumable.update(name, spellname, timestamp)

            if name == "Eye of C'Thun" and spellname == "Eye Beam":
                app.cthun_chain.add(timestamp, line)

            if name == "Sir Zeliek" and spellname == "Holy Wrath":
                app.fourhm_chain.add(timestamp, line)

            if spellname in INTERRUPT_SPELLS and targetname == "Kel'Thuzad":
                app.kt_frostbolt.parry(line)

            return True
        elif subtree.data == 'immune_ability_line':
            name = subtree.children[0].value
            spellname = subtree.children[1].value

            if spellname in app.hits_consumable.COOLDOWNS:
                app.hits_consumable.update(name, spellname, timestamp)

            return True
        elif subtree.data == 'immune_line':
            return True
        elif subtree.data == 'afflicted_line':
            targetname = subtree.children[0].value
            spellname = subtree.children[1].value

            if spellname == 'Decimate':
                app.gluth.add(line)

            if spellname == "Frost Blast":
                app.kt_frostblast.add(line)

            if targetname == 'Guardian of Icecrown':
                app.kt_guardian.add(line)

            return True
        elif subtree.data == 'is_absorbed_line':

            name = subtree.children[0].value
            spellname = subtree.children[1].value

            if spellname == "Corrupted Healing":
                app.nef_corrupted_healing.add(line)

            if name == "Eye of C'Thun" and spellname == "Eye Beam":
                app.cthun_chain.add(timestamp, line)

            if name == "Sir Zeliek" and spellname == "Holy Wrath":
                app.fourhm_chain.add(timestamp, line)

            if name == "Kel'Thuzad" and spellname == "Frost Blast":
                app.kt_frostblast.add(line)

            return True
        elif subtree.data == 'absorbs_line':
            targetname = subtree.children[0].value
            name = subtree.children[1].value
            spellname = subtree.children[2].value
            if spellname == 'Corrupted Healing':
                app.nef_corrupted_healing.add(line)
            return True
        elif subtree.data == 'removed_line':
            name = subtree.children[0].value
            spellname = subtree.children[1].value

            if name == 'Princess Huhuran' and spellname == 'Frenzy':
                app.huhuran.add(line)

            if name == 'Gluth' and spellname == 'Frenzy':
                app.gluth.add(line)

            return True
        elif subtree.data == 'suffers_line':
            targetname = subtree.children[0]
            # amount = subtree.children[1]
            # spell_damage_type = subtree.children[2].children[0].value
            # name = subtree.children[3]
            spellname = subtree.children[4]

            if spellname == 'Corrupted Healing':
                app.nef_corrupted_healing.add(line)


            return True
        elif subtree.data == 'fades_line':
            spellname = subtree.children[0].value
            targetname = subtree.children[1].value

            if targetname == 'Guardian of Icecrown':
                app.kt_guardian.add(line)

            return True
        elif subtree.data == 'slain_line':
            return True
        elif subtree.data == 'creates_line':
            return True
        elif subtree.data == 'is_killed_line':
            return True
        elif subtree.data == 'performs_on_line':
            return True
        elif subtree.data == 'performs_line':
            return True
        elif subtree.data == 'begins_to_perform_line':
            return True
        elif subtree.data == 'gains_extra_attacks_line':
            return True
        elif subtree.data == 'dodges_line':
            return True
        elif subtree.data == 'dodge_ability_line':
            return True
        elif subtree.data == 'reflects_damage_line':
            return True
        elif subtree.data == 'misses_line':
            return True
        elif subtree.data == 'misses_ability_line':
            return True
        elif subtree.data == 'falls_line':
            return True
        elif subtree.data == 'none_line':
            return True
        elif subtree.data == 'lava_line':
            return True
        elif subtree.data == 'slays_line':
            return True



    except LarkError as e:
        # parse errors ignored to try different strategies
        pass
    return False

def parse_log(app, filename):

    app.techinfo.get_file_size(filename)

    with io.open(filename, encoding='utf8') as f:
        linecount = 0
        skiplinecount = 0
        for line in f:
            linecount += 1

            if parse_line(app, line):
                continue

            skiplinecount += 1

            app.unparsed_logger.log(line)

        app.techinfo.get_line_count(linecount)
        app.techinfo.get_skipped_line_count(skiplinecount)

        app.unparsed_logger.flush()

class PrintConsumables:
    def __init__(self, player, pricedb, death_count):
        self.player = player
        self.pricedb = pricedb
        self.death_count = death_count

    def gold_string(self, price):
        copper = price % 100
        price = price // 100
        silver = price % 100
        price = price // 100
        gold = price
        s = ''

        first = True
        for amount, suffix in zip([gold, silver, copper], "gsc"):
            if amount:
                if not first: s+= ' '
                else: first = False
                s += f'{amount}{suffix}'
        return s


    def format_gold(self, consumable, count):
        total_price = 0

        components = CONSUMABLE_COMPONENTS.get(consumable)
        if not components:
            components = [(consumable, 1)]

        for component in components:
            consumable_component_name, multi = component

            itemid = NAME2ITEMID.get(consumable_component_name)
            if not itemid: continue
            price = self.pricedb.lookup(itemid)
            if not price: continue
            total_price += (price * multi * count)

        total_price //= CONSUMABLE_CHARGES.get(consumable, 1)
        if not total_price: return '', 0
        return self.gold_string(total_price), total_price

    def print(self, output):
        names = sorted(self.player.keys())
        for name in names:
            print(name, f'deaths:{self.death_count[name]}', file=output)
            cons = self.player[name]
            consumables = sorted(cons.keys())
            total_price = 0
            for consumable in consumables:
                count = cons[consumable]
                gold, price = self.format_gold(consumable, count)
                if gold:
                    gold = f'  ({gold})'
                total_price += price
                print('  ', consumable, count, gold, file=output)
            if not consumables:
                print('  ', '<nothing found>', file=output)
            elif total_price:
                print(file=output)
                print('  ', 'total spent:', self.gold_string(total_price), file=output)




def generate_output(app):

    output = io.StringIO()

    print("""Notes:
    - The report is generated using the combat log, which is far from perfect.
    - Use the report as evidence something DID happen and keep in mind the data is not exhaustive. In other words the report DOES NOT cover everything.
    - Some events are missing because the person logging wasn't in the instance yet or was too far away. This means inferring something DID NOT happen may be hard or impossible and requires extra care.
    - Jujus and many foods are not in the combat log, so they can't be easily counted.
    - Dragonbreath chili and goblin sappers have only "on hit" messages, so their usage is estimated based on timestamps and cooldowns.
    - Mageblood and some other mana consumes are "mana regeneration" in the combat log, can't tell them apart.
    - Lesser and greater protection potions don't have unique names, can't tell them apart.
    - Nordanaar Herbal Tea casts the same spell as Tea with Sugar, can't tell them apart.

    """, file=output)


    # remove pets
    for pet in app.pet_detect:
        if pet in app.player_detect:
            del app.player_detect[pet]

    # add players detected
    for name in app.player_detect:
        app.player[name]


    app.print_consumables.print(output)

    # bwl
    app.nef_corrupted_healing.print(output)
    # aq
    app.viscidus.print(output)
    app.huhuran.print(output)
    app.cthun_chain.print(output)
    # naxx
    app.gluth.print(output)
    app.fourhm_chain.print(output)
    app.kt_shadowfissure.print(output)
    app.kt_frostbolt.print(output)
    app.kt_frostblast.print(output)
    # app.kt_guardian.print(output)

    print(f"\n\nPets", file=output)
    for pet in app.pet_detect:
        print('  ', pet, 'owned by', app.pet_detect[pet], file=output)

    app.techinfo.print(output)

    print(output.getvalue())
    return output


def get_user_input():
    parser = argparse.ArgumentParser()
    parser.add_argument('logpath', help='path to WoWCombatLog.txt')
    parser.add_argument('--pastebin', action='store_true', help='upload result to a pastebin and return the url')
    parser.add_argument('--open-browser', action='store_true', help='used with --pastebin. open the pastebin url with your browser')

    parser.add_argument('--expert-log-unparsed-lines', action='store_true', help='create an unparsed.txt with everything that was not parsed')
    args = parser.parse_args()

    return args


class IxioUploader:
    def upload(self, output):
        data = output.getvalue().encode('utf8')

        username, password = 'summarize_consumes', 'summarize_consumes'
        auth = requests.auth.HTTPBasicAuth(username, password)
        response = requests.post(
            url='http://ix.io',
            files={'f:1': data},
            auth=auth,
            timeout=30,
        )
        print(response.text)
        if 'already exists' in response.text:
            return None
        if 'down for DDOS' in response.text:
            return None
        if response.status_code != 200:
            return None
        url = response.text.strip().split('\n')[-1]
        return url

class BpasteUploader:
    def upload(self, output):
        data = output.getvalue().encode('utf8')
        response = requests.post(
            url='https://bpaste.net/curl',
            data={'raw': data, 'expiry': '1month'},
            timeout=30,
        )
        if response.status_code != 200:
            return None
        lines = response.text.splitlines()
        for line in lines:
            if 'Raw URL' in line:
                url = line.split()[-1]
                return url


def upload_pastebin(output):
    url = BpasteUploader().upload(output)
    if url: return url
    url = IxioUploader().upload(output)
    return url

def open_browser(url):
    print(f'opening browser with {url}')
    webbrowser.open(url)





def main():

    args = get_user_input()

    app = create_app(
        expert_log_unparsed_lines=args.expert_log_unparsed_lines,
    )

    parse_log(app, filename=args.logpath)

    output = generate_output(app)

    if not args.pastebin: return
    url = upload_pastebin(output)

    if not args.open_browser: return
    if not url:
        print("didn't get a pastebin url")
        return
    open_browser(url)


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
# vim: set expandtab tabstop=4 shiftwidth=4:

# Hades Dialogue Player
# Copyright (C) 2022 CJ Kucera 
# 
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#     * Redistributions of source code must retain the above copyright
#       notice, this list of conditions and the following disclaimer.
#     * Redistributions in binary form must reproduce the above copyright
#       notice, this list of conditions and the following disclaimer in the
#       documentation and/or other materials provided with the distribution.
#     * Neither the name of the development team nor the
#       names of its contributors may be used to endorse or promote products
#       derived from this software without specific prior written permission.
# 
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
# ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL CJ KUCERA BE LIABLE FOR ANY
# DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
# (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
# ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

import io
import re
import os
import sys
import time
import json
import lzma
import argparse
import textwrap
import subprocess
import configparser

# Non-standard-lib.  From my `hades` venv
import slpp
import appdirs

class OggLibrary:

    ogg_re = re.compile(r'^(?P<num>\d+)\.(?P<vo>\S+)\.ogg$')

    def __init__(self, base_path):
        self.base_path = base_path
        self.oggs = {}
        for filename in os.listdir(self.base_path):
            if match := self.ogg_re.match(filename):
                self.oggs[match.group('vo')] = os.path.join(self.base_path, filename)

    def __contains__(self, key):
        return key in self.oggs

    def __getitem__(self, key):
        return self.oggs[key]

class NotACueException(Exception):
    pass

class NoCuesException(Exception):
    pass

class NoVOsException(Exception):
    pass

class Cue:

    def __init__(self, cue, text=None, delay=0, start_sound=None, choice=None):
        self.cue = cue
        self.text = text
        self.delay = delay
        self.start_sound = start_sound
        self.choice = choice

    @staticmethod
    def from_data(data, external_delay=0, choice=None):
        cue = None
        text = None
        delay = 0
        start_sound = None
        if 'Cue' in data:
            if data['Cue'] == '':
                cue = ''
            elif match := VO.vo_re.match(data['Cue']):
                cue = match.group('cue')
            else:
                print('WARNING: Cue without match: {}'.format(data['Cue']))
        if cue is None:
            raise NotACueException()
        if 'Text' in data:
            text = data['Text']
        if 'PreLineWait' in data:
            delay = float(data['PreLineWait'])
        if 'StartSound' in data:
            # TODO: Should maybe try and support this, though the two that I've
            # seen thus far (CerberusWhine and CerberusWhineSad) aren't actually
            # extracted properly, so it sort of doesn't matter yet.
            if match := VO.vo_re.match(data['StartSound']):
                start_sound = match.group('cue')
            else:
                if data['StartSound'].startswith('/SFX/'):
                    # Special-case here; we do see various /SFX/* sounds, like /SFX/DusaRattle
                    pass
                elif data['StartSound'] == '/Leftovers/World Sounds/MapZoomInShort':
                    # Another special-case, seen in Loot Data (this is the found-boon sfx)
                    pass
                else:
                    print('WARNING: Cue without match: {}'.format(data['StartSound']))
        delay += external_delay
        return Cue(cue,
                text=text,
                delay=delay,
                start_sound=start_sound,
                choice=choice,
                )

    def label(self):
        parts = []
        if self.cue == '':
            parts.append('(no audio)')
        else:
            parts.append(self.cue)
        if self.delay > 0:
            parts.append(f'({self.delay:0.1f}s delay)')
        if self.start_sound:
            parts.append(f'(StartSound: {self.start_sound})')
        if self.choice:
            parts.append(f'(choice: {self.choice})')
        return ' '.join(parts)


class VO:

    vo_re = re.compile(r'^/VO/(?P<cue>\S+)$')

    def __init__(self, data, file_map, config, label=None):

        self.file_map = file_map
        self.label = label
        self.config = config
        #print(f' - {label}')

        self.cues = []

        # In very basic voiceovers, this might just be a list of cues.  Much more
        # commonly it's a dict with a bunch of other params, and we have to do some
        # funky dict-pretending-to-be-a-list thing.
        if type(data) == list:
            # This is the most basic setup.  See NPC_Bouldy_01/BouldyGiftRepeatable01, for instance
            for cue_data in data:
                try:
                    self.cues.append(Cue.from_data(cue_data))
                except NotACueException:
                    pass
        elif type(data) == dict:
            # This is far more common -- we have various other dict entries

            # Check to see if there's an initial delay
            if 'PreLineWait' in data:
                initial_delay = float(data['PreLineWait'])
            else:
                initial_delay = 0

            # Check to see if this is a choice.  In NPCData there's two instances of this:
            #   1) Having a choice of songs to request from Orpheus (NPC_Orpheus_01 / OrpheusMiscMeeting03)
            #   2) Whether to accept Ambrosia returns from Dusa (NPC_Dusa_01 / BecameCloseWithDusaAftermath01)
            if 'ChoiceText' in data:
                choice_text = data['ChoiceText']
            else:
                choice_text = None

            # Loop through all the numeric indexes (this is the dict-pretending-to-be-a-list)
            for num in range(len(data.keys())):
                num_str = str(num)
                if num_str in data:
                    if type(data[num_str]) == dict \
                            and 'Choices' in data[num_str] \
                            and type(data[num_str]['Choices']) == list:
                        for choice_data in data[num_str]['Choices']:
                            try:
                                # We're technically losing initial_delay here.  Whatever.
                                # (also, nested choices might act weird, but there aren't any
                                # of those, so also Whatever.)
                                choice_vo = VO(choice_data, file_map, self.config)
                                self.cues.extend(choice_vo.cues)
                            except NoCuesException:
                                pass
                    else:
                        try:
                            self.cues.append(Cue.from_data(data[num_str], external_delay=initial_delay, choice=choice_text))
                            initial_delay = 0
                        except NotACueException:
                            pass

            # Add EndCue, if we have it
            end_cue = None
            if 'EndCue' in data and data['EndCue'] is not None:
                if match := VO.vo_re.match(data['EndCue']):
                    if 'EndWait' in data and data['EndWait'] is not None:
                        end_delay = float(data['EndWait'])
                    else:
                        end_delay = 0
                    self.cues.append(Cue(match.group('cue'), delay=end_delay, choice=choice_text))
                else:
                    print('WARNING: Cue without match: {}'.format(data['EndCue']))

            # Then EndVoiceLines is less-formal dialogue out in the main game world
            # (you've got control at this point)
            if 'EndVoiceLines' in data:
                if type(data['EndVoiceLines']) == dict:
                    try:
                        other_vo = VO(data['EndVoiceLines'], file_map, self.config)
                        self.cues.extend(other_vo.cues)
                    except NoCuesException:
                        pass
                elif type(data['EndVoiceLines']) == list:
                    # Seems like these just get played one after the other
                    for sub_data in data['EndVoiceLines']:
                        try:
                            other_vo = VO(sub_data, file_map, self.config)
                            self.cues.extend(other_vo.cues)
                        except NoCuesException:
                            pass
        else:
            print('WARNING: Unknown data type for voiceovers: {}'.format(type(data)))

        if len(self.cues) == 0:
            raise NoCuesException()

        # If there's a delay on the very first cue, ignore it
        self.cues[0].delay = 0

    def play(self, do_prompt=False):
        if self.label:
            print(self.label)
            print('-'*len(self.label))
        else:
            print('(no label)')
            print('----------')
        for cue in self.cues:
            print(f'  -> {cue.label()}')
            if cue.text is not None:
                for line in textwrap.wrap(cue.text,
                        initial_indent='     ',
                        subsequent_indent='     ',
                        ):
                    print(line)
            if cue.delay > 0:
                time.sleep(cue.delay)
            if cue.cue != '':
                if cue.cue in self.file_map:
                    command = list(self.config.media_player_list)
                    try:
                        brace_idx = command.index('{}')
                        command[brace_idx] = self.file_map[cue.cue]
                    except ValueError:
                        command.append(self.file_map[cue.cue])
                    subprocess.run(command, capture_output=True)
                else:
                    print(f'     ERROR: {cue.cue} not found')
            print('')

        if do_prompt:
            input('Enter to continue...')
            print('')

class Bank:

    def __init__(self, name, file_map, config, data):
        self.name = name
        self.file_map = file_map
        self.config = config
        self.combined = {}
        for key, label, obj in self.groups:
            if key in data and type(data[key]) == dict:
                for label, lineset in data[key].items():
                    try:
                        obj[label] = VO(lineset, file_map, config, label)
                        if label in self.combined:
                            # HermesPostEnding01 is our single known instance of this.
                            # Exists in SuperPriorityPickupTextLineSets and in
                            # PriorityPickupTextLineSets (and they *are* different).
                            # So there's one dialogue line that you can't get to via
                            # `combined`.
                            if label != 'HermesPostEnding01':
                                print(f'WARNING: {label} found in more than one category')
                        else:
                            self.combined[label] = obj[label]
                    except NoCuesException:
                        pass

        if all([len(d) == 0 for d in [g[2] for g in self.groups]]):
            raise NoVOsException()

    def __iter__(self):
        for _, _, group in self.groups:
            for val in group.values():
                yield val

    def __contains__(self, key):
        return key in self.combined

    def __getitem__(self, key):
        return self.combined[key]

class NPCBank(Bank):

    def __init__(self, name, file_map, config, data):
        self.interacts = {}
        self.repeatables = {}
        self.gifts = {}
        self.groups = [
                ('InteractTextLineSets', 'Interacts', self.interacts),
                ('RepeatableTextLineSets', 'Repeatables', self.repeatables),
                ('GiftTextLineSets', 'Gifts', self.gifts),
                ]
        super().__init__(name, file_map, config, data)

class EnemyBank(Bank):

    def __init__(self, name, file_map, config, data):
        self.supers = {}
        self.priorities = {}
        self.intros = {}
        self.basics = {}
        self.repeatables = {}
        self.groups = [
                ('BossPresentationIntroTextLineSets', 'Intros', self.intros),
                ('BossPresentationTextLineSets', 'Basic Conversations', self.basics),
                ('BossPresentationPriorityIntroTextLineSets', 'Priorities', self.priorities),
                ('BossPresentationSuperPriorityIntroTextLineSets', 'Super Priorities', self.supers),
                ('BossPresentationRepeatableTextLineSets', 'Repeatables', self.repeatables),
                ]
        super().__init__(name, file_map, config, data)

class LootBank(Bank):

    def __init__(self, name, file_map, config, data):
        self.duos = {}
        self.supers = {}
        self.priorities = {}
        self.pickups = {}
        self.boughts = {}
        self.rejections = {}
        self.makeups = {}
        self.gifts = {}
        self.groups = [
                ('PickupTextLineSets', 'Pickups', self.pickups),
                ('DuoPickupTextLineSets', 'Duos', self.duos),
                ('BoughtTextLines', 'Bought', self.boughts),
                ('GiftTextLineSets', 'Gifts', self.gifts),
                ('PriorityPickupTextLineSets', 'Priorities', self.priorities),
                ('SuperPriorityPickupTextLineSets', 'Super Priorities', self.supers),
                ('RejectionTextLines', 'Rejections', self.rejections),
                ('MakeUpTextLines', 'Makeups', self.makeups),
                ]
        super().__init__(name, file_map, config, data)

class Registry:

    def __init__(self, data_class, file_map, config, raw_data):
        self.config = config
        self.data = {}
        for section_name, section_data in raw_data.items():
            try:
                #print(f'Reading {section_name}')
                section = data_class(section_name, file_map, config, section_data)
                self.data[section_name] = section
            except NoVOsException:
                pass

    def copyfrom(self, other_registry):
        for k, v in other_registry.items():
            self.data[k] = v

    def __getitem__(self, key):
        return self.data[key]

    def items(self):
        return self.data.items()

    def keys(self):
        return self.data.keys()

    def values(self):
        return self.data.values()

class Dialogue:

    def __init__(self, config):

        self.config = config

        # Get our ogg library mapping
        self.oggs = OggLibrary(config.ogg_dir)

        # Make sure we have a cache dir
        if not os.path.exists(config.cache_dir):
            os.makedirs(config.cache_dir, exist_ok=True)

        # Make sure we have caches (LUA->JSON conversions) of our data files
        config.npcdata_json = self._get_json_cache(config.npcdata_script)
        config.enemydata_json = self._get_json_cache(config.enemydata_script)
        config.lootdata_json = self._get_json_cache(config.lootdata_script)

        # Read npcdata json and create NPC registry
        with lzma.open(config.npcdata_json) as df:
            npcdata = json.load(df)
        self.npc = Registry(NPCBank, self.oggs, self.config, npcdata['.NPCs'])

        # Read enemydata json and create enemy registry
        with lzma.open(config.enemydata_json) as df:
            enemydata = json.load(df)
        self.enemy = Registry(EnemyBank, self.oggs, self.config, enemydata['.Enemies'])

        # Our enemy data also includes one that's actually an NPC (Skelly/TrainingMelee)
        self.npc.copyfrom(Registry(NPCBank, self.oggs, self.config, enemydata['.Enemies']))

        # ... and our NPC data includes a few that enemy-style entries, too (Cerberus + Thanatos)
        self.enemy.copyfrom(Registry(EnemyBank, self.oggs, self.config, npcdata['.NPCs']))

        # Read lootdata json and create loot registry
        with lzma.open(config.lootdata_json) as df:
            lootdata = json.load(df)
        self.loot = Registry(LootBank, self.oggs, self.config, lootdata['LootData'])

    def _get_json_cache(self, script_filename):
        script_base = script_filename.rsplit('.', 1)[0]
        json_file = os.path.join(self.config.cache_dir, f'{script_base}.json.xz')
        if self.config.rebuild_cache or not os.path.exists(json_file):
            orig_file = os.path.join(self.config.lua_dir, script_filename)
            print(f'NOTICE: Converting {orig_file} to {json_file}')

            # SLPP doesn't really like these files as-is.  We need to wrap the
            # whole file in curly braces (so it's one big dict) and add commas
            # inbetween the various elements. This is far from a
            # general-purpose solution but it works well for us.  We're doing
            # some shenanigans with `injecting_comma` so that we don't put one
            # after the *final* dict closure, by accident.
            lua = io.StringIO()
            with open(orig_file, 'rt', encoding='utf-8') as df:
                injecting_comma = False
                print('{', file=lua)
                for line in df:
                    if injecting_comma:
                        print(',', file=lua)
                        injecting_comma = False
                    rstripped = line.rstrip()
                    if rstripped == '}':
                        injecting_comma = True
                        lua.write(line)
                    # Used to trim these lines out but it turns out it's not necessary
                    #elif rstripped == 'OverwriteTableKeys( EnemyData, UnitSetData.NPCs )':
                    #    pass
                    #elif rstripped == 'GlobalVoiceLines = GlobalVoiceLines or {}':
                    #    pass
                    else:
                        lua.write(line)
                print('}', file=lua)
            lua.seek(0)

            # temp -- write out
            #with open(os.path.join(self.config.cache_dir, f'{script_base}-edited.lua'), 'wt', encoding='utf-8') as odf:
            #    odf.write(lua.read())
            #lua.seek(0)

            # Convert to JSON
            data = slpp.slpp.decode(lua.read())
            with lzma.open(json_file, 'wt', encoding='utf-8') as odf:
                json.dump(data, odf, indent=2)

        return json_file

class BaseConfig(argparse.Namespace):

    # Config file handling
    config_dir = appdirs.user_config_dir('hades_dialogue', 'apocalyptech')
    config_file = os.path.join(config_dir, 'hades_dialogue.ini')
    save_config = False

    # Main config options
    ogg_dir = '/games/Steam/steamapps/common/Hades/Content/Audio/FMOD/Build/Desktop/tmp'
    lua_dir = '/games/Steam/steamapps/common/Hades/Content/Scripts'
    npcdata_script = 'NPCData.lua'
    enemydata_script = 'EnemyData.lua'
    lootdata_script = 'LootData.lua'
    npcdata_json = ''
    enemydata_json = ''
    lootdata_json = ''
    cache_dir = appdirs.user_cache_dir('hades_dialogue', 'apocalyptech')
    rebuild_cache = False
    media_player = 'mplayer'
    _media_player_list = []

    def __init__(self):
        self._saved_sections = {}
        if os.path.exists(self.config_file):
            cp = configparser.ConfigParser()
            cp.read(self.config_file)
            if 'main' in cp:
                known_sections = {'main'}
                if 'ogg_dir' in cp['main']:
                    self.ogg_dir = cp['main']['ogg_dir']
                else:
                    self.save_config = True
                if 'lua_dir' in cp['main']:
                    self.lua_dir = cp['main']['lua_dir']
                else:
                    self.save_config = True
                # Eh, don't bother with these
                #if 'npcdata_script' in cp['main']:
                #    self.npcdata_script = cp['main']['npcdata_script']
                #else:
                #    self.save_config = True
                #if 'enemydata_script' in cp['main']:
                #    self.enemydata_script = cp['main']['enemydata_script']
                #else:
                #    self.save_config = True
                #if 'lootdata_script' in cp['main']:
                #    self.lootdata_script = cp['main']['lootdata_script']
                #else:
                #    self.save_config = True
                if 'cache_dir' in cp['main']:
                    self.cache_dir = cp['main']['cache_dir']
                else:
                    self.save_config = True
                if 'media_player' in cp['main']:
                    self.media_player = cp['main']['media_player']
                else:
                    self.save_config = True
            else:
                self.save_config = True

            # Read any extra sections that implementing classes might use
            known_sections |= self._read_extra_config(cp)

            # Keep track of any sections that we don't know about
            for section in cp.sections():
                if section not in known_sections:
                    self._saved_sections[section] = cp[section]

    def _read_extra_config(self, cp):
        """
        Implement if necessary!  Returns a set containing the names
        of any extra config file sections which are controlled by
        the implementing util.
        """
        return set()

    @property
    def media_player_list(self):
        if not self._media_player_list:
            self._media_player_list = self.media_player.split()
        return self._media_player_list

    def config_file_present(self):
        return os.path.exists(self.config_file)

    def save(self):
        if not os.path.exists(self.config_dir):
            os.makedirs(self.config_dir, exist_ok=True)
        cp = configparser.ConfigParser()
        cp['main'] = {
                'ogg_dir': self.ogg_dir,
                'lua_dir': self.lua_dir,
                #'npcdata_script': self.npcdata_script,
                #'enemydata_script': self.enemydata_script,
                #'lootdata_script': self.lootdata_script,
                'cache_dir': self.cache_dir,
                'media_player': self.media_player,
                }
        for section, data in self._saved_sections.items():
            cp[section] = data
        self._write_extra_config(cp)
        with open(self.config_file, 'w') as odf:
            cp.write(odf)

    def _write_extra_config(self, cp):
        """
        Implement if necessary!
        """
        pass

class BaseApp:

    app_desc = 'Play Hades In-Game Dialogue'
    config_class = BaseConfig

    def __init__(self):

        self.config = self.config_class()

        parser = argparse.ArgumentParser(
                description=self.app_desc,
                formatter_class=argparse.ArgumentDefaultsHelpFormatter,
                )

        parser.add_argument('--ogg-dir',
                type=str,
                default=self.config.ogg_dir,
                help='Directory to find voiceover Ogg dirs',
                )

        parser.add_argument('--lua-dir',
                type=str,
                default=self.config.lua_dir,
                help='Directory to find the in-game Lua scripts',
                )

        # Kind of silly to have these as args; don't bother anymore.
        #parser.add_argument('--npcdata-script',
        #        type=str,
        #        default=self.config.npcdata_script,
        #        help='Filename of NPCData.lua script',
        #        )

        #parser.add_argument('--enemydata-script',
        #        type=str,
        #        default=self.config.enemydata_script,
        #        help='Filename of EnemyData.lua script',
        #        )

        #parser.add_argument('--lootdata-script',
        #        type=str,
        #        default=self.config.lootdata_script,
        #        help='Filename of LootData.lua script',
        #        )

        parser.add_argument('--cache-dir',
                type=str,
                default=self.config.cache_dir,
                help='Cache dir to hold LUA->JSON conversions',
                )

        parser.add_argument('--media-player',
                type=str,
                default=self.config.media_player,
                help="""Media player command to run, to play Oggs.  Can include
                    aguments.  If the filename to be played can't be the last
                    argument to the command, specify {} as one of the arguments
                    to replace the filename in question at that point.
                    """,
                )

        parser.add_argument('--save-config',
                action='store_true',
                help="""Save the chosen CLI args to the config file (this
                    happens automatically when the app is first run).
                    """,
                )

        parser.add_argument('-r', '--rebuild-cache',
                action='store_true',
                help='Rebuild the cache files',
                )

        # Add any extra args that implementing classes might need
        self._extra_args(parser)

        # Parse args!
        parser.parse_args(namespace=self.config)

        # Save out our config file if it's not present, or if we've
        # been told to
        if self.config.save_config or not self.config.config_file_present():
            self.config.save()
            print(f'NOTE: Saved config preferences to: {self.config.config_file}')

        # Read in all our Dialogue data
        self.dialogue = Dialogue(self.config)

        # Some convenience vars
        self.npc = self.dialogue.npc
        self.enemy = self.dialogue.enemy
        self.loot = self.dialogue.loot

    def _extra_args(self, parser):
        """
        Implement this if needed!
        """
        pass

    def run(self):
        """
        Implement this to actually Do Something.
        """
        pass


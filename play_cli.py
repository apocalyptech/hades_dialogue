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

from hdialogue.hdialogue import BaseApp, BaseConfig

class Config(BaseConfig):

    character = None
    loot = None
    enemy = None
    hardcode = False
    which = None

class App(BaseApp):

    app_desc = 'Play Hades In-Game Dialogue (CLI Version)'
    config_class = Config

    def _extra_args(self, parser):

        action_group = parser.add_mutually_exclusive_group(required=True)

        action_group.add_argument('-n', '--npc',
                type=str,
                help='Play dialogue from the specified NPC',
                )

        action_group.add_argument('-e', '--enemy',
                type=str,
                help='Play dialogue from the specified enemy',
                )

        action_group.add_argument('-l', '--loot',
                type=str,
                help='Play dialogue from the specified loot',
                )

        action_group.add_argument('-s', '--show',
                action='store_true',
                help='Show all NPC/Enemy/Loot IDs',
                )

        action_group.add_argument('-m', '--magic',
                action='store_true',
                help='Do "magic" hardcoded actions',
                )

        parser.add_argument('-w', '--which',
                type=str,
                help=""" Play the specified dialogue ID from inside the specified
                    npc/enemy/loot.  To get a list of available IDs, specify `list`.
                    """,
                )

    def play_registry(self, registry, choice, specific_notes=None):

        if self.config.which:

            # List all available dialogues
            if self.config.which == 'list':
                for vo in registry[choice]:
                    print(vo.label)

            # Play specific dialogues
            else:
                if specific_notes and self.config.which in specific_notes:
                    for line in specific_notes[self.config.which]:
                        print(line)
                registry[choice][self.config.which].play()
        else:
            # Play all dialogues
            for vo in registry[choice]:
                vo.play(do_prompt=True)

    def run(self):

        # NPC
        if self.config.npc:
            self.play_registry(self.npc, self.config.npc)

        # Enemy
        elif self.config.enemy:
            self.play_registry(self.enemy, self.config.enemy)

        # Loot
        elif self.config.loot:
            self.play_registry(self.loot, self.config.loot,
                    specific_notes={
                        'HermesPostEnding01': [
                            'WARNING: HermesPostEnding01 appears under two separate voiceover',
                            'categories.  Only one of them can be played using -w/--which',
                            ],
                        })

        # Show IDs
        elif self.config.show:
            print('NPCs')
            print('----')
            for name in sorted(self.npc.keys()):
                print(name)
            print('')
            print('Enemies')
            print('-------')
            for name in sorted(self.enemy.keys()):
                print(name)
            print('')
            print('Loot')
            print('----')
            for name in sorted(self.loot.keys()):
                print(name)
            print('')

        # Magic!
        elif self.config.magic:

            # Play some specific VOs
            #self.npc['NPC_Orpheus_01'].interacts['OrpheusFirstMeeting'].play()
            #self.npc['NPC_Orpheus_01'].interacts['OrpheusMiscMeeting03'].play()
            #self.npc['NPC_Sisyphus_01'].interacts['SisyphusAboutBouldy03'].play()
            #self.npc['NPC_Bouldy_01'].gifts['BouldyGiftRepeatable01'].play()
            #self.npc['NPC_Dusa_01'].interacts['BecameCloseWithDusaAftermath01'].play()
            #self.npc['AresUpgrade'].duos['AresWithPoseidon01'].play()

            # All Hypnos "consolation" messages
            #for label, vo in self.npc['NPC_Hypnos_01'].interacts.items():
            #    if label.startswith('HypnosConsolation'):
            #        vo.play(do_prompt=True)

            # All for a specific char
            #for vo in self.npc['NPC_Hades_01']:
            #for vo in self.npc['NPC_Hades_Story_01']:
            #for vo in self.npc['NPC_Orpheus_01']:
            #    vo.play(do_prompt=True)

            # All for a specific loot
            #for vo in self.loot['ArtemisUpgrade']:
            #    vo.play(do_prompt=True)

            # All for a specific enemy
            for vo in self.enemy['Harpy3']:
                vo.play(do_prompt=True)

def main():
    app = App()
    app.run()

if __name__ == '__main__':
    main()


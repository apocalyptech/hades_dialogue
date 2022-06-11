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

import os
import sys
import math
import enum
import appdirs
import itertools
import inputimeout

from rich import print, get_console
from rich.console import Console
from rich.theme import Theme
from rich.table import Table

from hdialogue.hdialogue import BaseApp, BaseConfig

def column_chunks(l, columns):
    """
    Divide up a given list `l` into the specified number of
    `columns`.  Yields each column in turn, as a list.  (Does
    *not* do any padding.)
    """
    length = len(l)
    if length == 0:
        yield []
    else:
        n = math.ceil(length/columns)
        for i in range(0, length, n):
            yield l[i:i + n]

class Config(BaseConfig):
    """
    Extra config we need.  We're saving these to the config file as
    well.
    """

    columns = 3
    min_rows = 15

    def _read_extra_config(self, cp):
        """
        Extra config to read from our file
        """
        if 'play_interactive' in cp:
            try:
                self.columns = int(cp['play_interactive']['columns'])
            except (ValueError, KeyError):
                self.save_config = True
            try:
                self.min_rows = int(cp['play_interactive']['min_rows'])
            except (ValueError, KeyError):
                self.save_config = True
        else:
            self.save_config = True
        return {'play_interactive'}

    def _write_extra_config(self, cp):
        """
        Extra vars to save to the config file
        """
        cp['play_interactive'] = {
                'columns': self.columns,
                'min_rows': self.min_rows,
                }

class Breadcrumb:
    """
    Helper to keep track of where we are in the object structure
    """

    def __init__(self, option, prev_options):
        self.option = option
        self.prev_options = prev_options

class Option:
    """
    A single option for the user
    """

    def __init__(self, label, data, pos, breadcrumb_label=None):
        self.label = label
        self.data = data
        self.pos = pos
        if breadcrumb_label is None:
            self.breadcrumb_label = label
        else:
            self.breadcrumb_label = breadcrumb_label

class Result(enum.Enum):
    """
    The result of processing user input, if any (the routine which handles
    user input might return None as well)
    """
    PLAY = enum.auto()
    AUTOPLAY = enum.auto()
    AUTOPLAY_ALL = enum.auto()

class App(BaseApp):
    """
    Interactive dialogue-playing app
    """

    app_desc = 'Play Hades In-Game Dialogue (Interactive Console Version)'
    config_class = Config

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Colorization tweaks, if present
        config_dir = appdirs.user_config_dir('py-rich', 'apocalyptech')
        rich_theme = os.path.join(config_dir, 'apoc.theme')
        if os.path.exists(rich_theme):
            t = Theme().read(rich_theme)
            get_console().push_theme(t)
            #print(t.styles)

    def _extra_args(self, parser):
        """
        Extra CLI args
        """

        parser.add_argument('-c', '--columns',
                type=int,
                default=self.config.columns,
                help='Columns to use when showing options',
                )

        parser.add_argument('-m', '--min-rows',
                type=int,
                default=self.config.min_rows,
                help='Minimum rows before columns get used',
                )

    def error(self, text):
        print(f'[bold red]{text}[/bold red]')
        print('')

    def process_options(self, options, stack, playing=True):
        """
        Present the user with a list of options, get their input, and then
        do what's needed.

        Note that this whole app makes a lot of assumptions about the data
        structure, and checks for the length of our Breadcrumb stack to make
        decisions about what to do.  Not especially flexible, but at the
        moment, all of our data is arranged like:

            Category -> Registry -> Bank -> VO

        ... so if we're at a stack length of 4, we're always at a voiceover,
        etc.  So, I never bothered making this more general-purpose.
        """

        if len(stack) == 4:
            num_options = len(stack[-1].prev_options)
        else:
            num_options = len(options)
        allow_prev = False
        allow_next = False
        allow_replay = False
        allow_autoplay = False
        if playing:
            allow_replay = True
            cur_pos = stack[-1].option.pos
            playlist_len = len(stack[-1].prev_options)
            if cur_pos > 0:
                allow_prev = True
            if cur_pos < (playlist_len-1):
                allow_next = True
                allow_autoplay = True
        if len(stack) == 3:
            allow_autoplay = True
        prompts = []
        if num_options > 0:
            prompts.append(f'[1-{num_options}]')
        if allow_autoplay:
            prompts.append('[a]utoplay')
        if allow_replay:
            prompts.append('[r]eplay')
        if allow_prev:
            prompts.append('[p]revious')
        if allow_next:
            prompts.append('[n]ext')
        if len(stack) > 0:
            prompts.append('[b]ack')
        prompts.append('[q]uit')
        prompt_txt = ', '.join(prompts) + '> '

        # Construct options table
        table = Table(
                show_header=False,
                box=None,
                highlight=True,
                pad_edge=False,
                )
        num_columns = 1
        table.add_column()
        while num_columns < self.config.columns:
            if num_options/num_columns > self.config.min_rows:
                table.add_column()
                num_columns += 1
            else:
                break
        for row_data in itertools.zip_longest(*column_chunks(options, num_columns)):
            new_row = []
            for item in row_data:
                if item is None:
                    new_row.append('')
                else:
                    new_row.append(f'{item.pos+1}) {item.label}')
            table.add_row(*new_row)

        while True:
            #for option in options:
            #    print(f'{option.pos+1}) {option.label}')
            print(table)
            print('')
            resp = input(prompt_txt)
            resp = resp.strip().lower()
            print('')
            if resp == 'q':
                sys.exit(0)
            elif len(stack) > 0 and resp == 'b':
                return stack.pop()
            elif allow_replay and resp == 'r':
                return Result.PLAY
            elif allow_prev and resp == 'p':
                stack[-1].option = stack[-1].prev_options[cur_pos-1]
                return Result.PLAY
            elif allow_next and resp == 'n':
                stack[-1].option = stack[-1].prev_options[cur_pos+1]
                return Result.PLAY
            elif allow_autoplay and resp == 'a':
                if len(stack) == 3:
                    # We're at the list of options, so advance into there
                    # and start playing
                    stack.append(Breadcrumb(options[0], options))
                    return Result.AUTOPLAY_ALL
                else:
                    # Already "at" an existing entry.  Advance the playlist,
                    # since we'll have already heard this one
                    stack[-1].option = stack[-1].prev_options[cur_pos+1]
                    return Result.AUTOPLAY
            elif num_options > 0:
                try:
                    intval = int(resp)
                except ValueError:
                    self.error('Unknown input, try again!')
                    continue
                if intval < 1 or intval > num_options:
                    self.error(f'Number must be from 1 to {num_options}')
                    continue
                if len(stack) == 4:
                    stack[-1].option = stack[-1].prev_options[intval-1]
                    return Result.PLAY
                else:
                    stack.append(Breadcrumb(options[intval-1], options))
                    return options[intval-1]
            else:
                self.error('Unknown input, try again!')
                continue

    def run(self):
        """
        Here we go!
        """

        print('')
        playing = False
        autoplaying = False
        options = None
        stack = []

        while True:

            if stack:
                header_txt = ' > '.join([s.option.breadcrumb_label for s in stack])
            else:
                header_txt = 'Choose a Category:'
            print(f'[bold]{header_txt}[/bold]')

            if options is None:

                # More hardcoding behavior based on Breadcrumb stack length.  c'est la vie!
                match len(stack):

                    case 0:
                        options = [
                                Option('NPCs', self.npc, 0),
                                Option('Enemies', self.enemy, 1),
                                Option('Loot', self.loot, 2),
                                ]

                    case 1:
                        options = []
                        for num, (name, bank) in enumerate(sorted(stack[-1].option.data.items())):
                            options.append(Option(name, bank, num))

                    case 2:
                        options = []
                        num = 0
                        for key, name, category in stack[-1].option.data.groups:
                            if len(category) > 0:
                                options.append(Option(name, category, num))
                                num += 1

                    case 3:
                        options = []
                        total =  len(stack[-1].option.data)
                        for num, (key, cue) in enumerate(stack[-1].option.data.items()):
                            options.append(Option(key, cue, num, '([dim cyan]{}[/dim cyan]/[dim cyan]{}[/dim cyan]) {}'.format(
                                num+1,
                                total,
                                key,
                                )))

                    case 4:
                        playing = True
                        options = []

                    case _:
                        self.error('Unknown state, exiting!')
                        sys.exit(1)

            # Play, if we've been told to
            if playing:
                print('')
                stack[-1].option.data.play()

            # If autoplaying, advance to the next and prompt...
            if autoplaying:
                if stack[-1].option.pos < (len(stack[-1].prev_options)-1):
                    try:
                        # TODO: Might be nice to colorize this prompt, but I suspect it's using
                        # sys.write() instead of print(), and rich tags don't get interpreted
                        result = inputimeout.inputimeout(prompt='Hit Enter within 2 seconds to stop autoplay...', timeout=2)
                        autoplaying = False
                    except inputimeout.TimeoutOccurred:
                        stack[-1].option = stack[-1].prev_options[stack[-1].option.pos+1]
                        print('')
                        continue
                else:
                    autoplaying = False
                    # If we're done autoplaying, we may as well go back to the
                    # audio select menu rather than staying on this one, since
                    # we got to the end.
                    options = stack.pop().prev_options
                    playing = False
                    # ... and skip to the next iteration so we draw the menu properly
                    continue

            # Get user input
            result = self.process_options(options, stack, playing=playing)

            # match/case doesn't like this very well
            if type(result) == Breadcrumb:
                # We went back
                options = result.prev_options
                playing = False
            elif type(result) == Option:
                # We chose something new
                options = None
            elif result == Result.PLAY:
                # Do nothing here, will play on the next refresh
                pass
            elif result == Result.AUTOPLAY:
                autoplaying = True
            elif result == Result.AUTOPLAY_ALL:
                autoplaying = True
                options = None
            else:
                raise RuntimeError('Unexpected result type: {}'.format(type(result)))

def main():
    app = App()
    app.run()

if __name__ == '__main__':
    main()


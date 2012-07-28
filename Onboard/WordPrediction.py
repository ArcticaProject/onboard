# -*- coding: utf-8 -*-
# Onboard is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# Onboard is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.
#
# Copyright © 2012, marmuta
#
# This file is part of Onboard.

from __future__ import division, print_function, unicode_literals

import sys
import os, errno
import time
import codecs
import re
from contextlib import contextmanager, closing
from traceback import print_exc
import dbus

try:
    from gi.repository import Atspi
except ImportError as e:
    _logger.info(_("Atspi unavailable, "
                   "word prediction may not be fully functional"))

import Onboard.pypredict as pypredict

from Onboard              import KeyCommon
from Onboard.AtspiUtils   import AtspiStateTracker
from Onboard.TextContext  import AtspiTextContext, InputLine
from Onboard.TextDomain   import TextClassifier
from Onboard.TextChanges  import TextSpan
from Onboard.SpellChecker import SpellChecker
from Onboard.Layout       import LayoutPanel
from Onboard.utils        import CallOnce, unicode_str, Timer, \
                                 get_keysym_from_name

### Config Singleton ###
from Onboard.Config import Config
config = Config()
########################

### Logging ###
import logging
_logger = logging.getLogger("WordPrediction")
###############


class WordPrediction:
    """ Keyboard mix-in for word prediction """

    def __init__(self, atspi_state_tracker = None):

        self.input_line = InputLine()
        self.atspi_text_context = AtspiTextContext(self, atspi_state_tracker)
        self.text_context = self.atspi_text_context  # initialize for doctests
        self._learn_strategy = LearnStrategyLRU(self)

        self._punctuator = Punctuator(self)
        self._spell_checker = SpellChecker()
        self._languagedb = LanguageDB(self)
        self._text_classifier = TextClassifier()
        self._wpservice  = None

        self._correction_choices = []
        self._correction_span = None
        self._prediction_choices = []
        self.word_infos = []

        self._hide_input_line = False
        self._word_list_bars = []
        self._text_displays = []
        
        self._focusable_count = 0

    def cleanup(self):
        self.commit_changes()
        if self.text_context:
            self.text_context.cleanup()

    def on_layout_loaded(self):
        self._word_list_bars = self.find_items_from_classes((WordListPanel,))
        self._text_displays = self.find_items_from_ids(("inputline",))
        self.enable_word_prediction(config.wp.enabled)
        self.update_spell_checker()

    def enable_word_prediction(self, enable):
        if enable:
            # only enable if there is a wordlist in the layout
            if self.get_word_list_bars():
                self._wpservice = WPService()
                self.apply_prediction_profile()
        else:
            self._wpservice = None

        # show/hide word-prediction buttons
        for item in self.get_word_list_bars():
            item.visible = enable
        for item in self.get_text_displays():
            item.visible = enable

        # show/hide other layout items
        layout = self.layout
        if layout:
            for item in layout.iter_items():
                if item.group == 'wordlist':
                    item.visible = enable
                elif item.group == 'nowordlist':
                    item.visible = not enable

        # Init text context tracking.
        # Keep track in and write to both contexts in parallel,
        # but read only from the active one.
        self.text_context = self.atspi_text_context
        self.text_context.enable(enable) # register AT-SPI listerners

    def on_word_prediction_enabled(self, enabled):
        """ Config callback for wp.enabled changes. """
        self.enable_word_prediction(enabled)
        self.update_ui()
        self.redraw()

    def get_word_list_bars(self):
        """
        Return all word list bars, so we don't have
        to look for them all the time.
        """
        return self._word_list_bars

    def get_text_displays(self):
        """
        Return all text feedback items, so we don't have
        to look for them all the time.
        """
        return self._text_displays

    def get_merged_model_names(self):
        """ Union of all system and user models """
        names = []
        if self._wpservice:
            system_models = set(self._wpservice.get_model_names("system"))
            user_models = set(self._wpservice.get_model_names("user"))
            names = list(system_models.union(user_models))
        return names

    def get_spellchecker_dicts(self):
        return self._spell_checker.get_supported_dict_ids()

    def send_release_key(self, key, button, event_type):
        if key.action_type == KeyCommon.CORRECTION_ACTION:
            self._insert_correction_choice(key, key.action)

        elif key.action_type == KeyCommon.WORD_ACTION:
            # no punctuation assistance on right click
            self._insert_prediction_choice(key, key.action, button != 3)

    def _insert_correction_choice(self, key, choice_index):
        """ spelling correction clicked """
        span = self._correction_span # span to correct
        self._replace_text(span.begin(), span.end(),
                           self.text_context.get_span_at_cursor().begin(),
                           self._correction_choices[choice_index])

    def _insert_prediction_choice(self, key, choice_index, allow_separator):
        """ prediction choice clicked """
        remainder = self._get_prediction_choice_remainder(choice_index)

        # should we add a separator character after the inserted word?
        cursor_span = self.text_context.get_span_at_cursor()
        context = cursor_span.get_text_until_span() + remainder
        separator = ""
        if config.wp.punctuation_assistance and \
           allow_separator:
            domain = self.text_context.get_text_domain()
            separator = domain.get_auto_separator(context)

        # type remainder + possible separator
        added_separator = self._insert_text_at_cursor(remainder, separator)
        self._punctuator.set_added_separator(added_separator)

    def on_before_key_press(self, key):
        self._punctuator.on_before_press(key)

    def on_after_key_release(self, key):
        self._punctuator.on_after_release(key)
        if not key.is_correction_key():
            self.expand_corrections(False)

    def enter_caps_mode(self):
        """
        Do what has to be done so that the next pressed
        charater will be capitalized.
        """
        # unlatch left shift
        for key in self.find_items_from_ids(["LFSH"]):
            if key.active:
                key.active = False
                key.locked = False
                if key in self._latched_sticky_keys:
                    self._latched_sticky_keys.remove(key)
                if key in self._locked_sticky_keys:
                    self._locked_sticky_keys.remove(key)

        # latch right shift for capitalization
        for key in self.find_items_from_ids(["RTSH"]):
            key.active = True
            key.locked = False
            if not key in self._latched_sticky_keys:
                self._latched_sticky_keys.append(key)
        self.vk.lock_mod(1)
        self.mods[1] = 1   # shift
        self.redraw()   # redraw the whole keyboard

    def update_spell_checker(self):
        backend = config.spell_check.backend \
                  if config.wp.enabled else None
        self._spell_checker.set_backend(backend)
        self.update_wordlists()

    def update_key_ui(self):
        self.update_inputline()
        self.update_wordlists()

        self.update_layout()

    def update_wordlists(self):
        for item in self.get_word_list_bars():
            item.create_keys(self._correction_choices, self._prediction_choices)
            self.redraw([item])

    def expand_corrections(self, expand):
        # collapse all expanded corrections
        for item in self.find_items_from_classes((WordListPanel)):
            if item.are_corrections_expanded():
                item.expand_corrections(expand)
                self.redraw([item])

    def get_active_lang_id(self):
        return config.word_suggestions.active_language

    def set_active_lang_id(self, lang_id):
        config.word_suggestions.active_language = lang_id

    def _auto_detect_language(self):
        """ find spelling suggestions for the word at or before the cursor """
        language = ""
        cursor_span = self.text_context.get_span_at_cursor()
        if cursor_span:
            language = self._text_classifier \
                           .detect_language(cursor_span.get_text())
        print("language=", repr(language))

    def _find_correction_choices(self):
        """ find spelling suggestions for the word at or before the cursor """
        self._correction_choices = []
        self._correction_span = None
        if self._spell_checker and config.spell_check.enabled:
            word_span = self._get_word_to_spell_check()
            if word_span:
                text_begin = word_span.text_begin()
                word = word_span.get_span_text()
                cursor = self.text_context.get_cursor()
                offset = cursor - text_begin # cursor offset into the word

                span, choices = \
                        self._spell_checker.find_corrections(word, offset)
                if choices:
                    self._correction_choices = choices
                    self._correction_span = TextSpan(span[0] + text_begin,
                                                     span[1] - span[0],
                                                     span[2],
                                                     span[0] + text_begin)
                #print("_find_correction_choices", word_span, word_span.get_text(), self._correction_choices, self._correction_span)

    def _find_prediction_choices(self):
        """ word prediction: find choices, only once per key press """
        self._prediction_choices = []
        if self._wpservice:
            context = self.text_context.get_context()

            # Are we at the capitalized first word of a sentence?
            tokens = self._wpservice.tokenize_context(context)
            capitalize = False
            if tokens:
                sentence_begin = len(tokens) >= 2 and tokens[-2] == "<s>"
                prefix = tokens[-1]
                capitalize = sentence_begin and prefix and prefix[0].isupper()

            choices = self._wpservice.predict(context,
                                      case_sensitive = not capitalize,
                                      accent_sensitive = \
                                            not config.wp.accent_insensitive)

            # Make all words start upper case
            if capitalize:
                for i, choice in enumerate(choices):
                    if choice:
                        choices[i] = choice[0].upper() + choice[1:]

            self._prediction_choices = choices

            # update word information for the input line display
            self.word_infos = self._wpservice.get_word_infos( \
                                               self.text_context.get_line())

    def _get_prediction_choice_remainder(self, index):
        """ returns the rest of matches[index] that hasn't been typed yet """
        if not self._wpservice:
            return ""
        text = self.text_context.get_context()
        word_prefix = self._wpservice.get_last_context_token(text)
        return self._prediction_choices[index][len(word_prefix):]

    def _get_word_to_spell_check(self):
        """
        Get the word to be spell checked.

        Doctests:
        >>> wp = WordPrediction()
        >>> wp._wpservice = WPService()
        >>> tc = wp.text_context

        # cursor at word end - suppress spelling suggestions while still typing
        >>> tc._span_at_cursor = TextSpan(8, 0, "binomial proportion")
        >>> wp.is_typing = lambda : True  # simulate typing
        >>> print(wp._get_word_to_spell_check())
        None
        """
        word_span = self._get_word_before_cursor()

        # Don't pop up spelling corrections if we're
        # currently typing the word.
        cursor = self.text_context.get_cursor()
        if word_span and \
           word_span.end() == cursor and \
           self.is_typing():
            word_span = None

        return word_span

    def _get_word_before_cursor(self):
        """
        Get the word at or before the cursor.

        Doctests:
        >>> wp = WordPrediction()
        >>> wp._wpservice = WPService()
        >>> tc = wp.text_context

        # cursor right in the middle of a word
        >>> tc.get_span_at_cursor = lambda : TextSpan(15, 0, "binomial proportion")
        >>> wp._get_word_before_cursor()
        TextSpan(9, 10, 'proportion', 9, None)

        # text at offset
        >>> tc.get_span_at_cursor = lambda : TextSpan(25, 0, "binomial proportion", 10)
        >>> wp._get_word_before_cursor()
        TextSpan(19, 10, 'proportion', 19, None)

        # cursor after whitespace - get the previous word
        >>> tc.get_span_at_cursor = lambda : TextSpan(9, 0, "binomial  proportion")
        >>> wp._get_word_before_cursor()
        TextSpan(0, 8, 'binomial', 0, None)
        """
        word_span = None
        cursor_span  = self.text_context.get_span_at_cursor()
        if cursor_span and self._wpservice:
            tokens, spans = self._wpservice.tokenize_text(cursor_span.get_text())

            cursor = cursor_span.begin()
            text_begin = cursor_span.text_begin()
            local_cursor = cursor_span.begin() - text_begin

            itoken = None
            for i, s in enumerate(spans):
                if s[0] > local_cursor:
                    break
                itoken = i

            if not itoken is None:
                token = unicode_str(tokens[itoken])

                # We're only looking for actual words
                if not token in ["<unk>", "<num>", "<s>"]:
                    b = spans[itoken][0] + text_begin
                    e = spans[itoken][1] + text_begin
                    word_span = TextSpan(b, e-b, token, b)

        return word_span

    def _replace_text(self, begin, end, cursor, new_text):
        """
        Replace text from <begin> to <end> with <new_text>,
        """
        with self.suppress_modifiers():
            length = end - begin
            offset = cursor - end  # offset of cursor to word end

            # delete the old word
            if offset >= 0:
                self.press_keysym("left", offset)
                self.press_keysym("backspace", length)
            else:
                self.press_keysym("delete", abs(offset))
                self.press_keysym("backspace", length - abs(offset))

            # insert the new word
            self.press_key_string(new_text)

            # move cursor back
            if offset >= 0:
                self.press_keysym("right", offset)

    def _insert_text_at_cursor(self, text, auto_separator = ""):
        """
        Insert a word (-remainder) and add a separator character as needed.
        """
        added_separator = ""
        if auto_separator:
            cursor_span = self.text_context.get_span_at_cursor()
            next_char = cursor_span.get_text(cursor_span.end(),
                                             cursor_span.end() + 1)
            remaining_line = self.text_context.get_line_past_cursor()

            # insert space if the cursor was on a non-space chracter or
            # the cursor was at the end of the line. The end of the line
            # in the terminal (e.g. in vim) may mean lot's of spaces until
            # the final new line.
            if next_char != auto_separator or \
               remaining_line.isspace():
                added_separator = auto_separator

        with self.suppress_modifiers():
            self.press_key_string(text)

            if auto_separator:
                if added_separator:
                    self.press_key_string(auto_separator)
                else:
                    self.press_keysym("right") # just skip over the existing space

        return added_separator

    def press_keysym(self, key_name, count = 1):
        keysym = get_keysym_from_name(key_name)
        for i in range(count):
            self.vk.press_keysym  (keysym)
            self.vk.release_keysym(keysym)

    def on_text_entry_activated(self):
        """ A different target widget has been focused """
        self.commit_changes()
        self._learn_strategy.on_text_entry_activated()

    def on_text_context_changed(self):
        """ The text of the target widget changed or the cursor moved """
        self._auto_detect_language()
        self._find_correction_choices()
        self._find_prediction_choices()
        self.expand_corrections(False)
        self.update_key_ui()
        self._learn_strategy.on_text_context_changed()

    def has_changes(self):
        """ Are there any changes to learn? """
        return self.text_context and \
               not self.text_context.get_changes().is_empty()

    def commit_changes(self):
        """ Learn all accumulated changes and clear them """
        if self.has_changes():
            self._learn_strategy.commit_changes()
            self._clear_changes()  # clear input line too

    def discard_changes(self):
        """
        Discard all changes that have accumulated for learning.
        """
        print("discarding changes")
        self._clear_changes()

    def _clear_changes(self):
        """
        Reset all contexts and clear all changes.
        """
        self.atspi_text_context.reset()
        self.input_line.reset()

    def apply_prediction_profile(self):
        if self._wpservice:
            # todo: settings
            system_models = ["lm:system:en"]
            user_models = ["lm:user:en"]
            auto_learn_model = user_models
            self._wpservice.set_models(system_models,
                                      user_models,
                                      auto_learn_model)

    def hide_input_line(self, hide = True):
        """
        Temporarily hide the input line to access keys below it.
        """
        self._hide_input_line = hide
        self.update_inputline()

    def update_inputline(self):
        """ Refresh the GUI displaying the current line's content """
        if self._wpservice:
            for key in self.get_text_displays():
                if self._hide_input_line:
                    key.visible = False
                else:
                    line = self.text_context.get_line()
                    if line:
                        key.raise_to_top()
                        key.visible = True
                    else:
                        line = ""
                        key.visible = False

                    key.set_content(line, self.word_infos,
                                    self.text_context.get_line_cursor_pos())
                self.redraw([key])

    def show_input_line_on_key_release(self, key):
        if self._hide_input_line and \
           not self._key_intersects_input_line(key):
            self._hide_input_line = False

    def _key_intersects_input_line(self, key):
        """ Check if key rect is intersecting the input line. """
        for item in self.get_text_displays():
            if item.get_border_rect().intersects(key.get_border_rect()):
                return True
        return False

    def on_focusable_gui_opening(self):
        """
        Turn off AT-SPI listeners while there is a dialog open.
        Onboard and occationally the whole desktop tend to lock up otherwise.
        Call this before dialog/popop menus are opened by Onboard itself.
        """
        if self._focusable_count == 0:
            self.atspi_state_tracker.freeze()
            self.atspi_text_context.freeze()
            print("freezing AT-SPI listeners")
        self._focusable_count += 1

    def on_focusable_gui_closed(self):
        """
        Call this after dialogs/menus have been closed.
        """
        self._focusable_count -= 1
        if self._focusable_count == 0:
            # Re-enable AT-SPI listeners
            self.atspi_state_tracker.thaw()
            self.atspi_text_context.thaw()
            print("thawing AT-SPI listeners")


class LearnStrategy:
    """
    Base class of learn strategies.
    """

    def __init__(self, tokenize = None):
        self._tokenize = tokenize if tokenize \
                         else pypredict.tokenize_text  # no D-Bus for tests

    def _learn_spans(self, spans):
        if config.wp.can_auto_learn():
            texts = self._get_learn_texts(spans)

            _logger.info("learning", texts)
            print("learning", texts)

            service = self._wp._wpservice
            for text in texts:
                service.learn_text(text, True)

    def _get_learn_texts(self, spans):
        token_sets = self._get_learn_tokens(spans)
        return [" ".join(tokens) for tokens in token_sets]

    def _get_learn_tokens(self, text_spans):
        """
        Get disjoint sets of tokens to learn.
        Tokens of overlapping or adjacent spans are joined.

        Doctests:
        >>> p = LearnStrategy()
        >>> p._get_learn_tokens([TextSpan(14, 2, "word1 word2 word3")])
        [['word3']]
        >>> p._get_learn_tokens([TextSpan( 3, 1, "word1 word2 word3"),
        ...                      TextSpan(14, 2, "word1 word2 word3")])
        [['word1'], ['word3']]
        >>> p._get_learn_tokens([TextSpan( 3, 4, "word1 word2 word3"),
        ...                      TextSpan(10, 1, "word1 word2 word3"),
        ...                      TextSpan(14, 2, "word1 word2 word3")])
        [['word1', 'word2', 'word3']]
        """
        text_spans = sorted(text_spans, key=lambda x: (x.begin(), x.end()))
        token_sets = []
        span_sets = []

        for text_span in text_spans:
            # Tokenize with one additional token in front so we can
            # spot and join adjacent token sets.
            tokens, spans, span_before = self._tokenize_span(text_span)

            merged = False
            if token_sets and tokens:
                prev_tokens = token_sets[-1]
                prev_spans  = span_sets[-1]
                link_span = span_before if span_before else spans[0]
                for i, prev_span in enumerate(prev_spans):
                    if prev_span == link_span:
                        k = i + 1 if span_before else i
                        token_sets[-1] = prev_tokens[:k] + tokens
                        span_sets[-1]  = prev_spans [:k] + spans
                        merged = True

            if not merged:
                token_sets.append(tokens)
                span_sets.append(spans)

        return token_sets

    def _tokenize_span(self, text_span, prepend_tokens = 0):
        """
        Extend spans text to word boundaries and return as tokens.
        Include <prepend_tokens> before the span.

        Doctests:
        >>> import Onboard.TextContext as tc
        >>> p = LearnStrategy()
        >>> p._tokenize_span(tc.TextSpan(0, 1, "word1 word2 word3"))
        (['word1'], [(0, 5)], None)
        >>> p._tokenize_span(tc.TextSpan(16, 1, "word1 word2 word3"))
        (['word3'], [(12, 17)], (6, 11))
        >>> p._tokenize_span(tc.TextSpan(8, 12, "word1 word2 word3"))
        (['word2', 'word3'], [(6, 11), (12, 17)], (0, 5))
        >>> p._tokenize_span(tc.TextSpan(5, 1, "word1 word2 word3"))
        ([], [], None)
        >>> p._tokenize_span(tc.TextSpan(4, 1, "word1 word2 word3"))
        (['word1'], [(0, 5)], None)
        >>> p._tokenize_span(tc.TextSpan(6, 1, "word1 word2 word3"))
        (['word2'], [(6, 11)], (0, 5))

        - text at offset
        >>> p._tokenize_span(tc.TextSpan(108, 1, "word1 word2 word3", 100))
        (['word2'], [(106, 111)], (100, 105))

        - prepend tokens
        >>> p._tokenize_span(tc.TextSpan(13, 1, "word1 word2 word3"), 1)
        (['word2', 'word3'], [(6, 11), (12, 17)], (0, 5))
        >>> p._tokenize_span(tc.TextSpan(1, 1, "word1 word2 word3"), 1)
        (['word1'], [(0, 5)], None)
        """
        tokens, spans = self._tokenize(text_span.get_text())

        itokens = []
        offset = text_span.text_begin()
        begin  = text_span.begin() - offset
        end    = text_span.end() - offset
        for i, s in enumerate(spans):
            if begin < s[1] and end > s[0]: # intersects?
                itokens.append(i)

        if prepend_tokens and itokens:
            first = itokens[0]
            n = min(prepend_tokens, first)
            itokens = list(range(first - n, first)) + itokens

        # Return an additional span for linking with other token lists:
        # span of the token before the first returned token.
        span_before = None
        if itokens and itokens[0] > 0:
            k = itokens[0] - 1
            span_before = (offset + spans[k][0], offset + spans[k][1])

        return([unicode_str(tokens[i]) for i in itokens],
               [(offset + spans[i][0], offset + spans[i][1]) for i in itokens],
               span_before)


class LearnStrategyLRU(LearnStrategy):
    """
    Delay learning individual spans of changed text to reduce the
    rate of junk entering the language model.
    """

    LEARN_DELAY  = 60  # seconds from last modification until spans are learned
    POLLING_TIME =  2  # seconds between polling for timed-out spans

    def __init__(self, wp):
        LearnStrategy.__init__(self,
                               lambda text: wp._wpservice.tokenize_text(text))
        self._wp = wp
        self._timer = Timer()

    def commit_changes(self):
        """ Learn and remove all changes """
        self._timer.stop()
        text_context = self._wp.text_context
        if text_context:
            changes = text_context.get_changes()
            spans = changes.get_spans() # by reference
            if spans:
                if spans and self._wp._wpservice:
                    self._learn_spans(spans)
                changes.clear()

    def commit_expired_changes(self):
        """
        Learn and remove spans that have reached their timeout.
        Keep the most recent span untouched,so it can be
        worked on indefinitely.
        """
        changes = self._wp.text_context.get_changes()
        spans = changes.get_spans()

        # find most recently update span
        most_recent = None
        for span in spans:
            if not most_recent or \
               most_recent.last_modified < span.last_modified:
                most_recent = span

        # learn expired spans
        expired_spans = []
        for span in list(spans):
            if not span is most_recent and \
               time.time() - span.last_modified >= self.LEARN_DELAY:
                expired_spans.append(span)
                changes.remove_span(span)
        self._learn_spans(expired_spans)

        return changes.get_spans()

    def on_text_entry_activated(self):
        pass

    def on_text_context_changed(self):
        changes = self._wp.text_context.get_changes()
        #print("on_text_context_changed", changes.get_spans(), changes.is_empty(), self._timer.is_running())
        if not changes.is_empty() and \
           not self._timer.is_running():
            # begin polling for text changes to learn every x seconds
            if 0:  # disabled for now
                self._timer.start(self.POLLING_TIME, self._poll_changes)

    def _poll_changes(self):
        remaining_spans = self.commit_expired_changes()
        return len(remaining_spans) != 0


class Punctuator:
    """
    Punctiation assistance. Mainly adds and removes spaces around
    punctuation depending on the user action immediately after word completion.
    """
    def __init__(self, wp):
        self._wp = wp
        self.reset()

    def reset(self):
        self._added_separator = False
        self._separator_removed = False
        self._capitalize = False

    def set_added_separator(self, separator = ""):
        self._added_separator = separator;

    def on_before_press(self, key):
        if config.wp.punctuation_assistance and \
           key.action_type == KeyCommon.KEYCODE_ACTION and \
           self._added_separator:
            self._added_separator = False

            char = key.get_label()
            if   char in ",:;":
                with self._wp.suppress_modifiers():
                    self._wp.press_keysym("backspace")
                self._separator_removed = True

            elif char in ".?!":
                with self._wp.suppress_modifiers():
                    self._wp.press_keysym("backspace")
                self._separator_removed = True
                self._capitalize = True

    def on_after_release(self, key):
        """
        Type the last part of the punctuation and possibly
        enable capitalization for the next key press
        """
        if config.wp.punctuation_assistance:
            if self._separator_removed:
                self._separator_removed = False
                self._wp.press_key_string(" ")

            if self._capitalize:
                self._capitalize = False
                self._wp.enter_caps_mode()


class WPService:
    """ Low level word predictor, D-Bus glue code. """

    def __init__(self):
        self.service = None
        self.recency_ratio = 50  # 0=100% frequency, 100=100% time

    def set_models(self, system_models, user_models, auto_learn_models):

        # auto learn language model must be part of the user models
        for model in auto_learn_models:
            if model not in user_models:
                auto_learn_models = None
                _logger.warning("No auto learn model selected. "
                                "Please setup learning first.")
                break

        self.models = system_models + user_models
        self.auto_learn_models = auto_learn_models

    def predict(self, context_line, case_sensitive = True,
                                    accent_sensitive = True):
        """ Find completion/prediction choices. """
        choices = []
        for retry in range(2):
            with self.get_service() as service:
                if service:
                    options = 0
                    if case_sensitive:
                        options |= pypredict.PredictionOptions.CASE_SENSITIVE
                    if accent_sensitive:
                        options |= pypredict.PredictionOptions.ACCENT_SENSITIVE

                    choices = service.predict(self.models, context_line, 50,
                                              options)
                break

        return choices

    def learn_text(self, text, allow_new_words):
        """ Count n-grams and add words to the auto-learn models. """
        if self.auto_learn_models:
            for retry in range(2):
                with self.get_service() as service:
                    if service:
                        tokens = service.learn_text(self.auto_learn_models,
                                                    text, allow_new_words)
                break

    def get_word_infos(self, text):
        """
        Return WordInfo objects for each word in text
        """

        # split text into words and lookup each word
        # count is 0 for no match, 1 for exact match or -n for partial matches
        tokens = []
        counts = []
        for retry in range(2):
            with self.get_service() as service:
                if service:
                    tokens, counts = service.lookup_text(self.models, text)
            break

        wis = []
        for i,t in enumerate(tokens):
            start, end, token = t
            word = text[start:end]
            wi = WordInfo(start, end, word)
            wi.exact_match   = any(count == 1 for count in counts[i])
            wi.partial_match = any(count  < 0 for count in counts[i])
            wi.ignored       = word != token
            wis.append(wi)

        return wis

    def tokenize_text(self, text):
        """
        Let the service find the words in text.
        """
        if 1:
            # avoid the D-Bus round-trip while we can
            tokens, spans = pypredict.tokenize_text(text)
        else:
            tokens = []
            spans = []
            for retry in range(2):
                with self.get_service() as service:
                    if service:
                        tokens, spans = service.tokenize_text(text)
                break
        return tokens, spans

    def tokenize_text_pythonic(self, text):
        """
        Let the service find the words in text.
        Return python types instead of dbus.Array/String/... .

        Doctests:
        # whitspace have to be respected in spans
        >>> p = WPService()
        >>> p.tokenize_text_pythonic("abc  def")
        (['abc', 'def'], [(0, 3), (5, 8)])
        """
        tokens, spans = self.tokenize_text(text)
        return( [unicode_str(t) for t in tokens],
                [(int(s[0]), int(s[1])) for s in spans] )

    def tokenize_context(self, text):
        """ let the service find the words in text """
        tokens = []
        if 1:
            # avoid the D-Bus round-trip while we can
            tokens = pypredict.tokenize_context(text)
        else:
            for retry in range(2):
                with self.get_service() as service:
                    if service:
                        tokens = service.tokenize_context(text)
                break
        return tokens

    def get_model_names(self, _class):
        """ Return the names of the available models. """
        names = []
        for retry in range(2):
            with self.get_service() as service:
                if service:
                    names = service.get_model_names(_class)
            break
        return [str(name) for name in names]

    def get_last_context_token(self, text):
        """ return the very last (partial) word in text """
        tokens = self.tokenize_context(text[-1024:])
        if len(tokens):
            return tokens[-1]
        else:
            return ""

    @contextmanager
    def get_service(self):
        try:
            if not self.service:
                bus = dbus.SessionBus()
                self.service = bus.get_object("org.onboard.WordPrediction",
                                              "/WordPredictor")
        except dbus.DBusException:
            #print_exc()
            _logger.error("Failed to acquire D-Bus prediction service")
            self.service = None
            yield None
        else:
            try:
                yield self.service
            except dbus.DBusException:
                print_exc()
                _logger.error("D-Bus call failed. Retrying.")
                self.service = None

class WordInfo:
    """ Word level information about found matches """

    exact_match = False
    partial_match = False
    ignored = False

    def __init__(self, start, end, word):
        self.start = start
        self.end   = end
        self.word  = word

    def __str__(self):
        return  "'%s' %d-%d unknown=%s exact=%s partial=%s ignored=%s" % \
                 (self.word, self.start, self.end,
                 self.unknown, self.exact_match, \
                 self.partial_match, self.ignored)


from gi.repository        import Gdk, Pango
from Onboard.KeyGtk       import RectKey, FullSizeKey, BarKey, WordKey
from Onboard.utils        import Rect
from Onboard.Layout       import LayoutBox

class WordListPanel(LayoutPanel):
    """ Panel populated with correction and prediction keys at run-time """

    def __init__(self):
        LayoutPanel.__init__(self)
        self._correcions_expanded = False

    def get_max_non_expanded_corrections(self):
        return 1

    def expand_corrections(self, expand):
        self._correcions_expanded = expand

    def are_corrections_expanded(self):
        return self._correcions_expanded

    def _get_button_width(self):
        return 10 * config.theme_settings.key_size / 100.0

    def create_keys(self, correction_choices, prediction_choices):
        """
        Dynamically create a variable number of buttons
        for word correction and prediction.
        """
        spacing = config.WORDLIST_BUTTON_SPACING[0]
        wordlist = self._get_child_button("wordlist")
        fixed_background = list(self.find_ids(["wordlist", "word",
                                               "correction"]))
        fixed_buttons    = list(self.find_ids(["expand-corrections",
                                               "language"]))
        if not wordlist:
            return []

        key_context = wordlist.context
        wordlist_rect = wordlist.get_rect()
        rect = wordlist_rect.copy()

        menu_button = self._get_child_button("language")
        button_width = self._get_button_width()
        if menu_button:
            rect.w -= button_width

        # font size is based on the height of the word list background
        font_size = WordKey.calc_font_size(key_context, rect.get_size())

        # hide the wordlist background when corrections create their own
        wordlist.set_visible(not correction_choices)

        # create correction keys
        keys, used_rect = self._create_correction_keys( \
                                        correction_choices,
                                        rect, wordlist,
                                        key_context, font_size)
        rect.x += spacing + used_rect.w
        rect.w -= spacing + used_rect.w

        # create prediction keys
        if not self.are_corrections_expanded():
            keys += self._create_prediction_keys(prediction_choices, rect,
                                                 key_context, font_size)

        # move the menu button to the end ot the bar
        if menu_button:
            r = wordlist_rect.copy()
            r.w = button_width
            r.x = wordlist_rect.right() - r.w
            menu_button.set_border_rect(r)

        # finally add all keys to the panel
        color_scheme = fixed_buttons[0].color_scheme
        for key in keys:
            key.color_scheme = color_scheme
        self.set_items(fixed_background + keys + fixed_buttons)

        return keys

    def _create_correction_keys(self, correction_choices, rect, wordlist,
                                    key_context, font_size):
        """
        Create all correction keys.
        """

        wordlist_rect = wordlist.get_rect()
        section_spacing = 1
        if not self.are_corrections_expanded():
            section_spacing += wordlist.get_fullsize_rect().w - wordlist_rect.w
            section_spacing = max(section_spacing, wordlist_rect.h * 0.1)

        # get button to expand/close the corrections
        button = self._get_child_button("expand-corrections")
        button_width = self._get_button_width()
        choices_rect = rect.copy()
        if button:
            choices_rect.w -= button_width + section_spacing

        # get template key for tooltips
        template = self._get_child_button("correction")

        # partition choices
        n = self.get_max_non_expanded_corrections()
        choices = correction_choices[:n]
        expanded_choices = correction_choices[n:] \
                           if self.are_corrections_expanded() else []

        # create unexpanded correction keys
        keys, used_rect = self._create_correction_choices(choices, choices_rect,
                                           key_context, font_size, 0, template)
        exp_keys = []
        bg_keys = []
        if keys:
            if button:
                # Move the expand button to the end
                # of the unexpanded corrections.
                r = used_rect.copy()
                r.x = used_rect.right()
                r.w = button_width
                button.set_border_rect(r)
                button.set_visible(True)

                used_rect.w += r.w

            # create background keys
            if self.are_corrections_expanded():
                x_split = wordlist_rect.right()
            else:
                x_split = used_rect.right()

            r = wordlist_rect.copy()
            r.w = x_split - r.x
            key = FullSizeKey("corrections-bg", r)
            key.theme_id = "wordlist" # same colors as wordlist
            key.sensitive = False
            bg_keys.append(key)

            r = wordlist_rect.copy()
            r.w = r.right() - x_split - section_spacing
            r.x = x_split + section_spacing
            key = FullSizeKey("wordlist-remaining-bg", r)
            key.theme_id = "wordlist" # same colors as wordlist
            key.sensitive = False
            bg_keys.append(key)

            used_rect.w += section_spacing

            # create expanded correction keys
            if expanded_choices:
                exp_rect = choices_rect.copy()
                exp_rect.x += used_rect.w
                exp_rect.w -= used_rect.w
                exp_keys, exp_used_rect = self._create_correction_choices( \
                                         expanded_choices, exp_rect,
                                         key_context, font_size, len(choices))
                keys += exp_keys
                used_rect.w += exp_used_rect.w
        else:
            button.set_visible(False)


        return bg_keys + keys + exp_keys, used_rect

    def _get_child_button(self, id):
        items = list(self.find_ids([id]))
        if items:
            return items[0]
        return None

    def _create_correction_choices(self, choices, rect,
                                   key_context, font_size,
                                   start_index = 0, template = None):
        """
        Dynamically create a variable number of buttons for word correction.
        """
        spacing = config.WORDLIST_BUTTON_SPACING[0]
        button_infos, filled_up, xend = self._fill_rect_with_choices(choices,
                                                rect, key_context, font_size)

        # create buttons
        keys = []
        x, y = 0.0, 0.0
        for i, bi in enumerate(button_infos):
            w = bi.w

            # create key
            r = Rect(rect.x + x, rect.y + y, w, rect.h)
            key = WordKey("", r)
            key.id = "correction" + str(i)
            key.labels = (bi.label[:],)*5
            key.font_size = font_size
            key.action_type = KeyCommon.CORRECTION_ACTION
            key.action = start_index + i
            if template:
                key.tooltip = template.tooltip
            keys.append(key)

            x += w + spacing  # move to begin of next button

        # return the actually used rect for all correction keys
        if keys:
            x -= spacing
        used_rect = rect.copy()
        used_rect.w = x

        return keys, used_rect

    def _create_prediction_keys(self, choices, wordlist_rect,
                               key_context, font_size):
        """
        Dynamically create a variable number of buttons for word prediction.
        """
        keys = []
        spacing = config.WORDLIST_BUTTON_SPACING[0]

        button_infos, filled_up, xend = self._fill_rect_with_choices(choices, wordlist_rect, key_context, font_size)
        if button_infos:
            all_spacings = (len(button_infos)-1) * spacing

            if filled_up:
                # Find a stretch factor that fills the remaining space
                # with only expandable items.
                length_nonexpandables = sum(bi.w for bi in button_infos \
                                            if not bi.expand)
                length_expandables = sum(bi.w for bi in button_infos \
                                         if bi.expand)
                length_target = wordlist_rect.w - length_nonexpandables \
                                - all_spacings
                scale = length_target / length_expandables \
                             if length_expandables else 1.0
            else:
                # Find the stretch factor that fills the available
                # space with all items.
                scale = (wordlist_rect.w - all_spacings) / \
                              float(xend - all_spacings - spacing)
            #scale = 1.0  # no stretching, left aligned

            # create buttons
            x,y = 0.0, 0.0
            for i, bi in enumerate(button_infos):
                w = bi.w

                # scale either all buttons or only the expandable ones
                if not filled_up or bi.expand:
                    w *= scale

                # create the word key with the generic id "word"
                key = WordKey("word" + str(i), Rect(wordlist_rect.x + x,
                                               wordlist_rect.y + y,
                                               w, wordlist_rect.h))
                key.labels = (bi.label[:],)*5
                key.font_size = font_size
                key.action_type = KeyCommon.WORD_ACTION
                key.action = i
                keys.append(key)

                x += w + spacing  # move to begin of next button

        return keys

    def _fill_rect_with_choices(self, choices, rect, key_context, font_size):
        spacing = config.WORDLIST_BUTTON_SPACING[0]
        x, y = 0.0, 0.0

        context = Gdk.pango_context_get()
        pango_layout = WordKey.get_pango_layout(context, None, font_size)
        button_infos = []
        filled_up = False
        for i,choice in enumerate(choices):

            # text extent in Pango units -> button size in logical units
            pango_layout.set_text(choice, -1)
            label_width, _label_height = pango_layout.get_size()
            label_width = key_context.scale_canvas_to_log_x(
                                                label_width / Pango.SCALE)
            w = label_width + config.WORDLIST_LABEL_MARGIN[0] * 2

            expand = w >= rect.h
            if not expand:
                w = rect.h

            # reached the end of the available space?
            if x + w > rect.w:
                filled_up = True
                break

            class ButtonInfo: pass
            bi = ButtonInfo()
            bi.label_width = label_width
            bi.w = w
            bi.expand = expand  # can stretch into available space?
            bi.label = choice[:]

            button_infos.append(bi)

            x += w + spacing  # move to begin of next button

        if button_infos:
            x -= spacing

        return button_infos, filled_up, x


import subprocess
import gettext
from xml.dom import minidom

class LanguageDB:
    """
    Keeps track of languages selectable in the language menu.
    """

    def __init__(self, wp):
        self._wp = wp
        self._locale_ids = []
        self._iso_codes = ISOCodes()

    def get_printable_name(self, lang_id):
        lang_code, country_code = self._split_lang_id(lang_id)
        name = self._iso_codes.get_translated_language_name(lang_code)
        if country_code:
            country = self._iso_codes.get_translated_country_name(country_code)
            if not country:
                country = country_code
            name += " (" + country + ")"
        return name

    def get_language_ids(self):
        """
        List of language_ids (ll_CC) that can be selected by the user.
        """
        return self._wp.get_merged_model_names()

    def _get_language_ids_in_locale(self):
        lang_ids = []
        for locale_id in self._get_locale_ids():
            lang_code, country_code, encoding = self._split_locale_id(locale_id)
            if lang_code and not lang_code in ["POSIX", "C"]:
                lang_id = lang_code
                if country_code:
                    lang_id += "_" + country_code
                lang_ids.append(lang_id)
        return lang_ids

    def _get_locale_ids(self):
        if not self._locale_ids:
            self._locale_ids = self._find_locale_ids()
        return self._locale_ids

    def _find_locale_ids(self):
        locale_ids = []
        try:
            locale_ids = subprocess.check_output(["locale", "-a"]) \
                                   .decode("UTF-8").split("\n")
        except OSError as e:
            _logger.error(_format("Failed to execute '{}', {}", \
                            " ".join(self.args), e))
        return [id for id in locale_ids if id]

    def _split_locale_id(self, locale_id):
        tokens = locale_id.split(".")
        lang_id = tokens[0] if len(tokens) >= 1 else ""
        encoding = tokens[1] if len(tokens) >= 2 else ""
        lang_code, country_code = self._split_lang_id(lang_id)
        return lang_code, country_code, encoding
    
    def _split_lang_id(self, lang_id):
        tokens = lang_id.split("_")
        lang_code    = tokens[0] if len(tokens) >= 1 else ""
        country_code = tokens[1] if len(tokens) >= 2 else ""
        return lang_code, country_code


class ISOCodes:
    """
    Load and translate ISO language and country codes.

    Doctests:
    >>> ic = ISOCodes()
    >>> ic.get_language_name("en")
    'English'
    >>> ic.get_country_name("DE")
    'Germany'
    """

    def __init__(self):
        self._languages = {}  # lowercase lang_ids
        self._countries = {}  # uppercase country_ids

        self._read_all()

    def get_language_name(self, lang_code):
        return self._languages.get(lang_code, "")

    def get_country_name(self, country_code):
        return self._countries.get(country_code, "")

    def get_translated_language_name(self, lang_code):
        return gettext.dgettext("iso_639", self.get_language_name(lang_code))

    def get_translated_country_name(self, country_code):
        country_name = self.get_country_name(country_code)
        if not country_name:
            country_name = country_code
        return gettext.dgettext("iso_3166", country_name)

    def _read_all(self):
        self._read_languages()
        self._read_countries()

    def _read_languages(self):
        with open("/usr/share/xml/iso-codes/iso_639.xml") as f:
            dom = minidom.parse(f).documentElement
            for node in dom.getElementsByTagName("iso_639_entry"):

                lang_code = self._get_attr(node, "iso_639_1_code")
                if not lang_code:
                    lang_code = self._get_attr(node, "iso_639_2T_code")

                lang_name = self._get_attr(node, "name", "")

                if lang_code and lang_name:
                    self._languages[lang_code] = lang_name

    def _read_countries(self):
        with open("/usr/share/xml/iso-codes/iso_3166.xml") as f:
            dom = minidom.parse(f).documentElement
            for node in dom.getElementsByTagName("iso_3166_entry"):

                country_code = self._get_attr(node, "alpha_2_code")
                country_name = self._get_attr(node, "name")

                if country_code and country_name:
                    self._countries[country_code.upper()] = country_name

    @staticmethod
    def _get_attr(node, name, default = ""):
        attr = node.attributes.get(name)
        if attr:
            return attr.value
        return ""


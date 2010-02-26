/*
This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.

Author: marmuta <marmvta@gmail.com>
*/

#ifndef LM_H
#define LM_H

#include <stdint.h>
#include <wchar.h>
#include <vector>
#include <map>
#include <algorithm>


// break into debugger
// step twice to come back out of the raise() call into known code
#define BREAK raise(SIGINT)

//#undef NDEBUG
#define ASSERT(c) assert(c)
//#ifndef NDEBUG
//#define ASSERT(c) assert(c)
//#else
//#define ASSERT(c) /*c*/
//#endif

#ifndef ALEN
#define ALEN(a) ((int)(sizeof(a)/sizeof(*a)))
#endif

void* MemAlloc(size_t size);
void MemFree(void* p);

//typedef uint32_t WordId;
typedef uint16_t WordId;
#define WIDNONE ((WordId)-1)

template <class T>
int binsearch(const std::vector<T>& v, T key)
{
    typename std::vector<T>::const_iterator it = lower_bound(v.begin(), v.end(), key);
    if (it != v.end() && *it == key)
        return int(it - v.begin());
    return -1;
}

//------------------------------------------------------------------------
// Dictionary - contains the vocabulary of the language model
//------------------------------------------------------------------------

class Dictionary
{
    public:
        Dictionary()
        {
            clear();
        }

        void clear();

        WordId word_to_id(const wchar_t* word);
        wchar_t* id_to_word(WordId wid);
        std::vector<WordId> words_to_ids(const wchar_t** word, int n);

        WordId add_word(const wchar_t* word);
        bool contains(const wchar_t* word) {return word_to_id(word) != WIDNONE;}

        void prefix_search(const wchar_t* prefix, std::vector<WordId>& wids,
                           WordId min_wid = 0);
        void prefix_search(const wchar_t* prefix, std::vector<wchar_t*>& words,
                           WordId min_wid = 0);

        int get_num_word_types() {return words.size();}

        void reserve_words(int count);
        uint64_t get_memory_size();

    protected:
        // binary search for index of insertion point (std:lower_bound())
        int search_index(const wchar_t* word)
        {
            int lo = 0;
            int hi = sorted.size();
            while (lo < hi)
            {
                int mid = (lo+hi)>>1;
                if (wcscmp(words[sorted[mid]], word) < 0)
                    lo = mid + 1;
                else
                    hi = mid;
            }
            return lo;
        }

    protected:
        std::vector<wchar_t*> words;
        std::vector<WordId> sorted;
};


//------------------------------------------------------------------------
// LanguageModel - base class of language models
//------------------------------------------------------------------------

class LanguageModel
{
    public:
        enum ControlWords
        {
            UNKNOWN_WORD_ID = 0,
            BEGIN_OF_SENTENCE_ID,
            END_OF_SENTENCE_ID,
            NUMBER_ID,
            NUM_CONTROL_WORDS
        };

        enum PredictOptions
        {
            FILTER_CONTROL_WORDS = 1<<0, // suppress <s>, <num>, ...
            SORT                 = 1<<1, // sort by weight
            NORMALIZE            = 1<<2, // explicit normalization for
                                         // overlay and loglinint, everthing
                                         // else ought to be normalized already.
            DEFAULT_OPTIONS      = FILTER_CONTROL_WORDS|SORT,
        };

        enum Error 
        {
            ERR_NOT_IMPL = -1,
            ERR_NONE = 0, 
            ERR_FILE, 
            ERR_MEMORY, 
            ERR_NUMTOKENS,
            ERR_ORDER, 
            ERR_COUNT, 
            ERR_UNEXPECTED_EOF,
        };
        
    public:
        LanguageModel()
        {
        }

        virtual ~LanguageModel()
        {
        }

        virtual void clear()
        {
            dictionary.clear();
        }

        // never fails
        virtual WordId word_to_id(const wchar_t* word)
        {
            WordId wid = dictionary.word_to_id(word);
            if (wid == WIDNONE)
                return UNKNOWN_WORD_ID;   // map to always existing <unk> entry
            return wid;
        }

        std::vector<WordId> words_to_ids(const std::vector<wchar_t*>& words)
        {
            std::vector<WordId> wids;
            std::vector<wchar_t*>::const_iterator it;
            for(it=words.begin(); it!=words.end(); it++)
                wids.push_back(word_to_id(*it));
            return wids;
        }

        // never fails
        const wchar_t* id_to_word(WordId wid)
        {
            static const wchar_t* not_found = L"";
            wchar_t* w = dictionary.id_to_word(wid);
            if (!w)
                return not_found;
            return w;
        }

        typedef struct {const wchar_t* word; double p;} Result;
        virtual void predict(std::vector<LanguageModel::Result>& results,
                             const std::vector<wchar_t*>& context,
                             int limit=-1,
                             uint32_t options = DEFAULT_OPTIONS);

        virtual double get_probability(const wchar_t* const* ngram, int n);

        virtual int get_num_word_types() {return dictionary.get_num_word_types();}

        virtual Error load(const char* filename) = 0;
        virtual Error save(const char* filename) = 0;

    protected:
        const wchar_t* split_context(const std::vector<wchar_t*>& context,
                                 std::vector<wchar_t*>& history);
        virtual void get_candidates(const wchar_t*prefix,
                                 std::vector<WordId>& wids,
                                 bool filter_control_words=true)
        {}
        virtual void get_probs(const std::vector<WordId>& history,
                                 const std::vector<WordId>& words,
                                 std::vector<double>& probabilities)
        {}
        Error read_utf8(const char* filename, wchar_t*& text);

    public:
        Dictionary dictionary;
};


//------------------------------------------------------------------------
// NGramModel - base class of n-gram language models, may go away
//------------------------------------------------------------------------

class NGramModel : public LanguageModel
{
    public:
        NGramModel()
        {
            order = 0;
        }

        virtual int get_order()
        {
            return order;
        }

        virtual void set_order(int n)
        {
            order = n;
            clear();
        }

        #ifndef NDEBUG
        void print_ngram(const std::vector<WordId>& wids);
        #endif

    public:
        int order;
};

#endif


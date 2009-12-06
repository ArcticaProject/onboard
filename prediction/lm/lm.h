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
        std::vector<WordId> words_to_ids(const wchar_t** word, int n);
        wchar_t* id_to_word(WordId wid);

        WordId add_word(const wchar_t* word);

        void search_prefix(const wchar_t* prefix, std::vector<WordId>& wids);

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
        static const int UNKNOWN_WORD_ID = 0;

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
        virtual void predict(const wchar_t* const* context, int n, int limit, std::vector<Result>& results);
        virtual double get_probability(const wchar_t* const* ngram, int n) = 0;

        virtual int get_num_word_types() {return dictionary.get_num_word_types();}

        virtual int load(const char* filename) = 0;
        virtual int save(const char* filename) = 0;

    protected:
        virtual void get_candidates(const wchar_t*prefix, std::vector<WordId>& wids) = 0;
        virtual void get_probs(const std::vector<WordId>& history,
                               const std::vector<WordId>& words,
                               std::vector<double>& probabilities) = 0;
    public:
        Dictionary dictionary;
};


//------------------------------------------------------------------------
// LanguageModelNGram - base class of n-gram language models, may go away
//------------------------------------------------------------------------

class LanguageModelNGram : public LanguageModel
{
    public:
        LanguageModelNGram()
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

        virtual int get_ngram_count(const wchar_t* const* ngram, int n) = 0;

        #ifndef NDEBUG
        void print_ngram(const std::vector<WordId>& wids);
        #endif

    public:
        int order;
};

#endif


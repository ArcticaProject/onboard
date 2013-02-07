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

#include <stdlib.h>
#include <stdio.h>
#include <algorithm>
#include <cmath>
#include <string>
#include <wctype.h>

#include "lm.h"
#include "accent_transform.h"

using namespace std;


// sorts an index array according to values from the cmp array, descending
template <class T, class TCMP>
void stable_argsort_desc(vector<T>& v, const vector<TCMP>& cmp)
{
    // Shellsort in place; stable, fast for already sorted arrays
    int i, j, gap;
    int n = v.size();
    T t;

    for (gap = n/2; gap > 0; gap >>= 1)
    {
        for (i = gap; i < n; i++)
        {
            for (j = i-gap; j >= 0; j -= gap)
            {
                if (!(cmp[v[j]] < cmp[v[j+gap]]))
                    break;

                // Swap p with q
                t = v[j+gap];
                v[j+gap] = v[j];
                v[j] = t;
            }
        }
    }
}

// Replacement for wcscmp with optional case-
// and/or accent-insensitive comparison.
class PrefixCmp
{
    public:
        PrefixCmp(const wchar_t* _prefix, uint32_t _options)
        {
            if (_prefix)
                prefix = _prefix;
            options = _options;

            if (options & LanguageModel::CASE_INSENSITIVE)
                transform (prefix.begin(), prefix.end(), prefix.begin(), op_lower);
            if (options & LanguageModel::ACCENT_INSENSITIVE)
                transform (prefix.begin(), prefix.end(), prefix.begin(), op_remove_accent);
        }

        int matches(const wchar_t* s)
        {
            wint_t c1, c2;
            const wchar_t* p = prefix.c_str();
            size_t n = prefix.size();

            wint_t c = s[0];
            if (c)
            {
                if ((options & LanguageModel::IGNORE_CAPITALIZED) && 
                    iswupper(c))
                    return false;

                if ((options & LanguageModel::IGNORE_NON_CAPITALIZED) &&
                    !iswupper(c))
                    return false;
            }

            if (n == 0)
                return true;

            do
            {
                c1 = (wint_t) *s++;
                if (options & LanguageModel::CASE_INSENSITIVE)
                    c1 = (wint_t) towlower(c1);
                if (options & LanguageModel::ACCENT_INSENSITIVE)
                    c1 = (wint_t) op_remove_accent(c1);

                c2 = (wint_t) *p++;

                if (c1 == L'\0' || c1 != c2)
                    return false;
            } while (--n > 0);

            return c1 == c2;
        }

    private:
        static wint_t op_lower(wint_t c)
        {
            return towlower(c);
        }

        static wint_t op_remove_accent(wint_t c)
        {
            if (c <= 0x7f)
                return c;

            wint_t i = lookup_transform(c, _accent_transform,
                                            ALEN(_accent_transform));
            if (i<ALEN(_accent_transform) && 
                _accent_transform[i][0] == c)
                return _accent_transform[i][1];
            return c;
        }

        static int lookup_transform(wint_t c, wint_t table[][2], int len)
        {
            int lo = 0;
            int hi = len;
            while (lo < hi)
            {
                int mid = (lo+hi)>>1;
                if (table[mid][0] < c)
                    lo = mid + 1;
                else
                    hi = mid;
            }
            return lo;
        }

    private:
        wstring prefix;
        uint32_t options;
};


//------------------------------------------------------------------------
// Dictionary - contains the vocabulary of the language model
//------------------------------------------------------------------------

void Dictionary::clear()
{
    vector<wchar_t*>::iterator it;
    for (it=words.begin(); it < words.end(); it++)
        MemFree(*it);

    vector<wchar_t*>().swap(words);  // clear and really free the memory
    vector<WordId>().swap(sorted);
}

// Reserve an exact number of items to avoid unessarily
// overallocating memory when loading language models
void Dictionary::reserve_words(int count)
{
    clear();
    words.reserve(count);
    sorted.reserve(count);
}

// Lookup the given word and return its id, binary search
WordId Dictionary::word_to_id(const wchar_t* word)
{
    int index = search_index(word);
    if (index >= 0 && index < (int)sorted.size())
    {
        WordId wid = sorted[index];
        if (wcscmp(words[wid], word) == 0)
            return wid;
    }
    return WIDNONE;
}

vector<WordId> Dictionary::words_to_ids(const wchar_t** word, int n)
{
    vector<WordId> wids;
    for(int i=0; i<n; i++)
        wids.push_back(word_to_id(word[i]));
    return wids;
}

// return the word for the given id, fast index lookup
wchar_t* Dictionary::id_to_word(WordId wid)
{
    if (0 <= wid && wid < (int)words.size())
        return words[wid];
    return NULL;
}

// Add a word to the dictionary
WordId Dictionary::add_word(const wchar_t* word)
{
    wchar_t* w = (wchar_t*)MemAlloc((wcslen(word) + 1) * sizeof(wchar_t));
    if (!w)
        return -1;
    wcscpy(w, word);

    WordId wid = (WordId)words.size();
    words.push_back(w);

    // bottle neck here, this is rather inefficient
    // everything else just appends, this inserts
    int index = search_index(w);
    sorted.insert(sorted.begin()+index, wid);

    //printf("%ls %d %d %d\n", w, wid, (int)words.size(), (int)words.capacity());

    return wid;
}

// Find all word ids of words starting with prefix
void Dictionary::prefix_search(const wchar_t* prefix,
                               std::vector<WordId>* wids_in,  // may be NULL
                               std::vector<WordId>& wids_out,
                               uint32_t options)
{
    int prefix_len = prefix ? wcslen(prefix) : 0;
    WordId min_wid = (options & LanguageModel::INCLUDE_CONTROL_WORDS) \
                     ? 0 : LanguageModel::NUM_CONTROL_WORDS;

    // filter the given word ids only
    if (wids_in)
    {
        PrefixCmp cmp = PrefixCmp(prefix, options);
        std::vector<WordId>::const_iterator it;
        for(it = wids_in->begin(); it != wids_in->end(); it++)
        {
            int wid = *it;
            if (wid >= min_wid &&
                cmp.matches(words[wid]))
                wids_out.push_back(wid);
        }
    }
    else
    // exhaustive search through the dictionary
    if (prefix_len == 0 || options & LanguageModel::FILTER_OPTIONS)
    {
        PrefixCmp cmp = PrefixCmp(prefix, options);
        int size = words.size();
        for (int i = min_wid; i<size; i++)
            if (cmp.matches(words[i]))
                wids_out.push_back(i);
    }
    // Binary search for the first match then linearly collect
    // all subsequent matches.
    // Collation order is unspecified since we want to support multiple
    // languages simultaneausly. This means binary searching for the
    // first word is safe only in xx_sensitive mode.
    else
    {
        int index = search_index(prefix);
        int size = sorted.size();
        for (int i=index; i<size; i++)
        {
           // wint_t towlower (wint_t wc);
            WordId wid = sorted[i];
            if (wcsncmp(words[wid], prefix, prefix_len) != 0)
                break;
            if (wid >= min_wid)  // filter control words
                wids_out.push_back(wid);
        }
    }
}

// lookup word
// return value: 0 = no match
//               1 = exact match
//              -n = number of partial matches (prefix search)
int Dictionary::lookup_word(const wchar_t* word)
{
    // binary search for the first match
    // then linearly collect all subsequent matches
    int len = wcslen(word);
    int size = sorted.size();
    int count = 0;

    int index = search_index(word);

    // try exact match first
    if (index >= 0 && index < (int)sorted.size())
    {
        WordId wid = sorted[index];
        if (wcscmp(words[wid], word) == 0)
            return 1;
    }

    // then count partial matches
    for (int i=index; i<size; i++)
    {
        WordId wid = sorted[i];
        if (wcsncmp(words[wid], word, len) != 0)
            break;
        count++;
    }
    return -count;
}

// Estimate a lower bound for the memory usage of the dictionary.
// This includes overallocations by std::vector, but excludes memory
// used for heap management and possible heap fragmentation.
uint64_t Dictionary::get_memory_size()
{
    uint64_t sum = 0;

    uint64_t d = sizeof(Dictionary);
    sum += d;

    uint64_t w = 0;
    for (unsigned i=0; i<words.size(); i++)
        w += sizeof(wchar_t) * (wcslen(words[i]) + 1);
    sum += w;

    uint64_t wc = sizeof(wchar_t*) * words.capacity();
    sum += wc;

    uint64_t sc = sizeof(WordId) * sorted.capacity();
    sum += sc;

    #ifndef NDEBUG
    printf("dictionary object: %12ld Byte\n", d);
    printf("strings:           %12ld Byte (%u)\n", w, (unsigned)words.size());
    printf("words.capacity:    %12ld Byte (%u)\n", wc, (unsigned)words.capacity());
    printf("sorted.capacity:   %12ld Byte (%u)\n", sc, (unsigned)sorted.capacity());
    printf("Dictionary total:  %12ld Byte\n", sum);
    #endif

    return sum;
}


//------------------------------------------------------------------------
// LanguageModel - base class of all language models
//------------------------------------------------------------------------

void LanguageModel::predict(std::vector<LanguageModel::Result>& results,
                            const std::vector<wchar_t*>& context,
                            int limit, uint32_t options)
{
    int i;

    if (!context.size())
        return;

    // split context into history and completion-prefix
    vector<wchar_t*> h;
    const wchar_t* prefix = split_context(context, h);
    vector<WordId> history = words_to_ids(h);

    // get candidate words, completion
    vector<WordId> wids;
    get_candidates(history, prefix, wids, options);

    // calculate probability vector
    vector<double> probabilities(wids.size());
    get_probs(history, wids, probabilities);

    // prepare results vector
    int result_size = wids.size();
    if (limit >= 0 && limit < result_size)
        result_size = limit;
    results.clear();
    results.reserve(result_size);

    if (!(options & NO_SORT)) // allow to skip sorting for calls from another model, i.e. linint
    {
        // sort by descending probabilities
        vector<int32_t> argsort(wids.size());
        for (i=0; i<(int)wids.size(); i++)
            argsort[i] = i;
        stable_argsort_desc(argsort, probabilities);

        // merge word ids and probabilities into the return array
        for (i=0; i<result_size; i++)
        {
            int index = argsort[i];
            Result result = {id_to_word(wids[index]),
                             probabilities[index]};
            results.push_back(result);
        }
    }
    else
    {
        // merge word ids and probabilities into the return array
        for (int i=0; i<result_size; i++)
        {
            Result result = {id_to_word(wids[i]),
                             probabilities[i]};
            results.push_back(result);
        }
    }
}

// Return the probability of a single n-gram.
// This is very inefficient, not optimized for speed at all, but it's
// basically only there for entropy testing anyway and not involved in
// actual word prediction tasks..
double LanguageModel::get_probability(const wchar_t* const* ngram, int n)
{
#if 1
    if (n)
    {
        // clear the last word of the context
        vector<wchar_t*> ctx((wchar_t**)ngram, (wchar_t**)ngram+n-1);
        const wchar_t* word = ngram[n-1];
        ctx.push_back((wchar_t*)L"");

        // run an unlimited prediction to get normalization right for
        // overlay and loglinint
        vector<Result> results;
        predict(results, ctx, -1, NORMALIZE);

        double psum = 0;
        for (int i=0; i<(int)results.size(); i++)
            psum += results[i].p;
        if (fabs(1.0 - psum) > 1e5)
            printf("%f\n", psum);

        for (int i=0; i<(int)results.size(); i++)
            if (wcscmp(results[i].word, word) == 0)
                return results[i].p;
        for (int i=0; i<(int)results.size(); i++)
            if (wcscmp(results[i].word, L"<unk>") == 0)
                return results[i].p;
    }
    return 0.0;
#else
    // split ngram into history and last word
    const wchar_t* word = ngram[n-1];
    vector<WordId> history;
    for (int i=0; i<n-1; i++)
        history.push_back(word_to_id(ngram[i]));

    // build candidate word vector
    vector<WordId> wids(1, word_to_id(word));

    // calculate probability
    vector<double> vp(1);
    get_probs(history, wids, vp);

    return vp[0];
#endif
}

// split context into history and prefix
const wchar_t* LanguageModel::split_context(const vector<wchar_t*>& context,
                                                  vector<wchar_t*>& history)
{
    int n = context.size();
    wchar_t* prefix = context[n-1];
    for (int i=0; i<n-1; i++)
        history.push_back(context[i]);
    return prefix;
}

LanguageModel::Error LanguageModel::read_utf8(const char* filename, wchar_t*& text)
{
    text = NULL;

    FILE* f = fopen(filename, "r,ccs=UTF-8");
    if (!f)
    {
        #ifndef NDEBUG
        printf( "Error opening %s\n", filename);
        #endif
        return ERR_FILE;
    }

    int size = 0;
    const size_t bufsize = 1024*1024;
    wchar_t* buf = new wchar_t[bufsize];
    if (!buf)
        return ERR_MEMORY;

    while(1)
    {
        if (fgetws(buf, bufsize, f) == NULL)
            break;
        int l = wcslen(buf);
        text = (wchar_t*) realloc(text, (size + l + 1) * sizeof(*text));
        wcscpy (text + size, buf);
        size += l;
    }

    delete [] buf;

    return ERR_NONE;
}


//------------------------------------------------------------------------
// NGramModel - base class of n-gram language models, may go away
//------------------------------------------------------------------------

#ifndef NDEBUG
void NGramModel::print_ngram(const std::vector<WordId>& wids)
{
    for (int i=0; i<(int)wids.size(); i++)
    {
        printf("%ls(%d)", id_to_word(wids[i]), wids[i]);
        if (i<(int)wids.size())
            printf(" ");
    }
    printf("\n");
}
#endif




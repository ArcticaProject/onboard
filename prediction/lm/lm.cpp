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

#include "lm.h"

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

// Look up the given word and return its id, binary search
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
void Dictionary::search_prefix(const wchar_t* prefix, vector<WordId>& wids)
{
    // binary search for the first match
    // then linearly collect all subsequent matches
    int len = wcslen(prefix);
    int size = sorted.size();
    int index = search_index(prefix);
    for (int i=index; i<size; i++)
    {
        WordId wid = sorted[i];
        if (wcsncmp(words[wid], prefix, len) != 0)
            break;
        wids.push_back(wid);
    }
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
// LanguageModel - base class of language models
//------------------------------------------------------------------------

void LanguageModel::predict(const wchar_t* const* context, int n, int limit,
                            vector<LanguageModel::Result>& results)
{
    int i;

    if (!n)
        return;

    // split context into history and prefix
    const wchar_t* prefix = context[n-1];
    vector<WordId> history;
    for (i=0; i<n-1; i++)
        history.push_back(word_to_id(context[i]));

    // get candidate words
    vector<WordId> wids;
    get_candidates(prefix, wids);

    // calculate probability vector
    vector<double> probabilities(wids.size());
    get_probs(history, wids, probabilities);

    // sort by descending probabilities
    vector<int32_t> argsort(wids.size());
    for (i=0; i<(int)wids.size(); i++)
        argsort[i] = i;
    stable_argsort_desc(argsort, probabilities);

    // merge word indexes and probabilities into the return array
    int result_size = wids.size();
    if (limit >= 0 && limit < result_size)
        result_size = limit;

    results.resize(result_size);
    for (i=0; i<result_size; i++)
    {
        Result result = {id_to_word(wids[argsort[i]]),
                         probabilities[argsort[i]]};
        results[i] = result;
    }
}


//------------------------------------------------------------------------
// LanguageModelNGram - base class of n-gram language models, may go away
//------------------------------------------------------------------------

#ifndef NDEBUG
void LanguageModelNGram::print_ngram(const std::vector<WordId>& wids)
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



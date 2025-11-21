# A rant about why you shouldn't use ElasticSearch for sql sized problems

A bit of info incase you want to modify this script or are looking at doing this yourself (ie, they change the API endpoints but keep the backend somewhat similar)

Behind the scenes, their API calls an elasticSearch endpoint. ElasticSearch (ES from now on) has a limit of only returning 10,000 documents. Now, you might be thinking "just paginate the results, duhh!" - but sadly its not that simple. ES uses 'from' and 'size' to do pagination, however the sum of the two values must be under 10,000. This means if we are paginating with chunks of 50, requesting 9900 to 9950 will work, 9950 to 9999 will work, but even asking for 9950 to 10000 will throw an error.

The normal solution is to request the data to be sorted, and use `search_after`, but their API proxy will conform the results to an expected output (stripping any additional keys we might have requested). Because of this, we cant use this method.

To make things more complicated, doing some black box testing against their API gives non-deterministic output. for instance, asking for sounds 0-5 might return the ids: [1,2,3,4,5] but then asking for sounds from 1-3 will return [765, 623, 102]... so even with pagination, it would be hard to know we are getting all the sounds. (just kidding, i looked into this a bit more after implementing the solution defined below. Turns out that the BBC devs were somewhat aware of this, and on the backend set "from" to be your input*10, probably to try and work around this limitation, but ES doesn't care since it sees the multiplied value, so it doesn't work to solve the issue!)

So, this project takes another approach. The search API has 3 filters we can control, a sound category, a continent catagory, and a duration window. Instead of relying on pagination, we instead permutate all possible filters and request the max returned amount allowed (documents 0 - 9999). We build our own datasource off of that, and de-duplicate the results, then use that for downloading.

The permutation method is needed since searching for EVERY sound in a catagory might return more bytes of data then their API proxy will handle (which results in an internal server error), as well as the fact that some sound catagories have more than 10,000 sounds in them. Sadly the data on the BBC website does not fit 1:1 with their filters. for instance, searching for all sounds in the way described above only yields 16291 sounds total (if we only search for each possible permutation). Most of this discrepancy is because some sounds dont have a continent specified. Instead, we choose a catagory, permutate all possible durations with any continent set, and then unset the duration field and permutate all continents. This gets us pretty close (32109 out of the possible 33066 as of writing this README).

I thank the BBC for the free sounds, but your dev team might want more help... they are aparently aware of the limitations on the API, but slapped a "only allow the top 300 results to be shown" bandaid on an "our API can't handle pagination" problem. (on top of other oddities, like using a GET request for an endpoint specific to a catagory for the first 10 results, before returning to the generic POST endpoint with filters for follow up requests). No hate, but this jank is what spurred the project :) - hopefully the recorders in the field are ok with 784 of their sounds being hidden unless you know what to search for!

heres some stats, you nerd:
sounds under "Nature" that don't fit the filter options for continent or duration: 77
sounds that don't have a catagory: 707

# A rant about Davinci Resolve and their sound library

The Davinci Resolve manual does not mention how to add this data manually, and a very old post on the forums mentions it pulls the info from the audio file its self. Audio metadata is a whole can of worms, so my guess is that the feature broke at some point, and no one raised a stink about it... so here we are, manually modifying the sqlite db. oh well, at least it works

So, the SoundLib.db file is a sqlite3 database. Theres ~150 tables inside, but almost all of them are empty. There are two tables that contain info about the sound files we imported though... `FLAssetBaseClip` and `FLAssetBaseFile`. If you look at them, it seems that the description is stored in BaseClip, and the file is stored in BaseFile. Well, turns out neither have the absolute path to the file, and both contain the filename... so we can just ignore BaseFile and just modify the description in BaseClip. Easy!
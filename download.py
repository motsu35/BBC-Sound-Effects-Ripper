# Download.py
#
# Author: Motsu / MethodicalMaker
# License: WTFPL

from time import sleep
import pickle
import requests
import json
from tqdm import tqdm
import os
import frozendict
import humanize
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import as_completed
import shutil
from urllib3.util.retry import Retry
from pydub import AudioSegment
from requests.adapters import HTTPAdapter
import sqlite3

# Audio metadata stuff
from mutagen.mp3 import MP3
from mutagen.flac import FLAC
from mutagen.wave import WAVE
from mutagen.id3 import COMM

# Compression level for FLAC output. 0 is fastest but largest file size. see https://boomspeaker.com/flac-compression-levels-explained/ for info on setting this.
#   I opted for a reasonably small file since the sound library is HUGE
FLAC_COMPRESSION_LEVEL = 5

# use this if debugging to avoid hammering the search API
USE_PICKEL_SEARCH_DB = False

SEARCH_URL = "https://sound-effects-api.bbcrewind.co.uk/api/sfx/search"

filters = {
    "category": {
        "url": "https://sound-effects-api.bbcrewind.co.uk/api/sfx/categoryAggregations",
        "values": None # to be filled programatically
    },
    "continent": {
        "url": "https://sound-effects-api.bbcrewind.co.uk/api/sfx/continentAggregations",
        "values": None
    },
    "duration": {
        "url": "https://sound-effects-api.bbcrewind.co.uk/api/sfx/durationAggregations",
        "values": None
    }
}

# Add retry logic:
session = requests.Session()
retries = Retry(total=5, backoff_factor=1)
session.mount('https://', HTTPAdapter(max_retries=retries))


# POST request data format. We modify this when scraping filter info and hitting the search API. probably dont modify this unless you understand what the code is doing
searchRequestData = {
    "criteria": {
        "from":0,
        "size":9999,
        "tags":None,
        "categories":None,
        "durations":None,
        "continents":None,
        "sortBy":None,
        "source":None,
        "recordist":None,
        "habitat":None
    }
}

def buildSearchRequestData(data):
    # the api expects `null` (unquoted) for values that are not set
    #   by default the requests lib will just ommit a value if it is set to None in a POST request.
    # example data from web frontend: --data-raw '{"criteria":{"from":0,"size":50,"tags":null,"categories":null,"durations":null,"continents":null,"sortBy":null,"source":null,"recordist":null,"habitat":null}}'
    return json.dumps({
        "criteria": {k: ("null" if v is None else v) for k, v in data["criteria"].items()}
    }).replace('"null"', 'null')

def doSearchRequest(searchRequestData):
    ret = requests.post(SEARCH_URL, data = buildSearchRequestData(searchRequestData), headers={'Content-Type': 'application/json'})
    ret.raise_for_status()
    parsedRet = json.loads(ret.content.decode("utf-8"))
    deduped_search = set([frozendict.deepfreeze(r) for r in parsedRet["results"]])

    return deduped_search, len(parsedRet["results"])

def buildFileInfo(soundInfo):
    soundIDString = soundInfo["id"]
    catagoryString = ", ".join([c["className"] for c in soundInfo["categories"]]) or "Uncatagorized"
    descriptionString = soundInfo["description"]
    tagString = ", ".join(soundInfo["tags"])
    additionalData = "\t"+"\n\t".join([f"{k} - {v}" for k,v in soundInfo["additionalMetadata"].items() if v])
    
    #print(f"TITLE: {catagoryString} - {soundIDString}")
    #print(f"TAGS:\n\t{tagString}\nDESCRIPTION:\n\t{descriptionString}\nMETADATA:\n{additionalData}")
    #print("\n\n\n")
    return f"TAGS:\n\t{tagString}\nDESCRIPTION:\n\t{descriptionString}\nMETADATA:\n{additionalData}"

def buildSearchFilters():
    for filter_type in filters:
        ret = requests.post(filters[filter_type]["url"], headers={'Content-Type': 'application/json'}, data = buildSearchRequestData(searchRequestData))
        ret.raise_for_status()
        parsedRet = json.loads(ret.content.decode("utf-8"))
        filters[filter_type]["values"] = {k: v["doc_count"] for k, v in parsedRet["aggregations"].items()}

def getTotalSoundCount():
    # initial call to search, just to get the total sounds reported by BBC
    searchRequestData["criteria"]["size"] = 1 
    ret = requests.post(SEARCH_URL, data = buildSearchRequestData(searchRequestData), headers={'Content-Type': 'application/json'})
    ret.raise_for_status()
    parsedRet = json.loads(ret.content.decode("utf-8"))

    # we only did a size of 1 for the initial total num sounds search
    searchRequestData["criteria"]["size"] = 9999

    return parsedRet["total"]

def doFileDownload(soundInfo, outputFolder, fileType):
    soundIDString = soundInfo["id"]
    catagoryString = ", ".join([c["className"] for c in soundInfo["categories"]]) or "Uncatagorized"

    if fileType == "flac":
        # flac requires conversion, so handle it slightly differently... its prooooobably ok that this is also being multithreadded :)
        tmpFileName = f"{catagoryString} - {soundIDString}.wav"
        tmpFilePath = os.path.join(os.path.join(outputFolder, "_tmp"), tmpFileName)
        flacFileName = f"{catagoryString} - {soundIDString}.flac"
        flacPath = os.path.join(outputFolder, flacFileName)
        with requests.get(f"https://sound-effects-media.bbcrewind.co.uk/wav/{soundIDString}.wav", stream=True) as request:
            with open(tmpFilePath, 'wb') as file:
                shutil.copyfileobj(request.raw, file)
        try:
            # We can add comments metadata during the conversion instead of doing it in another step like we do below for non-flac downloads
            AudioSegment.from_wav(tmpFilePath).export(flacPath, format="flac", parameters=["-compression_level", str(FLAC_COMPRESSION_LEVEL)], tags={"Comments": buildFileInfo(soundInfo)})
        except Exception:
            print(f"Failed to convert {tmpFilePath} to FLAC. Keeping WAV file instead!")
            shutil.move(tmpFilePath, os.path.join(outputFolder, tmpFileName))
        else:
            os.remove(tmpFilePath)

    else:
        fileName = f"{catagoryString} - {soundIDString}.{fileType}"
        filePath = os.path.join(outputFolder, fileName)
        with requests.get(f"https://sound-effects-media.bbcrewind.co.uk/{fileType}/{soundIDString}.{fileType}", stream=True) as request:
            with open(filePath, 'wb') as file:
                shutil.copyfileobj(request.raw, file)
        if fileType == "mp3":
            audioFile = MP3(filePath)
        elif fileType == "wav":
            audioFile = WAVE(filePath)
        audioFile["COMM"] = COMM(encoding=3, text=[buildFileInfo(soundInfo)])
        audioFile["TXXX:comment"] = COMM(encoding=3, text=[buildFileInfo(soundInfo)])
        audioFile.save()



def buildDavinciSoundLibraryDB(allSounds):
    print("Great! first we need to set up the sounds in Davinci. Please refer to the README.md section on doing so, then return here and press enter to continue...")
    input()
    soundLibDBPath = input("Enter the path to SoundLib.db: ")

    while not os.path.exists(soundLibDBPath) and not os.path.isfile(soundLibDBPath):
        print("The path you entered was incorrect, make sure you specify the full path, including SoundLib.db")
        soundLibDBPath = input("Enter the path to SoundLib.db: ")

    sqlCon = sqlite3.connect(soundLibDBPath)
    sqlCur = sqlCon.cursor()

    for soundInfo in tqdm(allSounds):
        soundIDString = soundInfo["id"]
        catagoryString = ", ".join([c["className"] for c in soundInfo["categories"]]) or "Uncatagorized"
        # Davinci replaces underscores with spaces in the db. idk why, but they do. We only have underscores in the catagory.
        catagoryString = catagoryString.replace("_", " ")
        dbNameFieldValue = f"{catagoryString} - {soundIDString}"
        sqlCur.execute(f"UPDATE FLAssetBaseClip SET description = ? WHERE name = ?", (buildFileInfo(soundInfo), dbNameFieldValue))
    sqlCon.commit()




def scrapeBBCSearchAPI(allSounds):
    # Stats variables so we can check that we get all sounds for a given category
    category_total_sounds = None

    # Start building our local db of potential sounds to download.
    for category in (pbar_category := tqdm(filters["category"]["values"], leave=False)):
        pbar_category.set_description(f"Searching sounds in category: {category}")
        searchRequestData["criteria"]["categories"] = [category]

        category_total_sounds = 0

        # All the catagories are small enough to just download all files from them, except for nature
        if category != "Nature":
            searchRequestData["criteria"]["durations"] = None
            deduped_results, non_deduped_search_result_count = doSearchRequest(searchRequestData)
            category_total_sounds = non_deduped_search_result_count
            allSounds |= deduped_results
        else:
            # Nature is a huge catagory, so get fancy with it! (applying this method to all catagories reduces some of the results)
            natureSounds = set()
            for duration in (pbar_duration := tqdm(filters["duration"]["values"], leave=False)):
                pbar_duration.set_description(" "*4*2 + f"duration: {duration}")
                
                searchRequestData["criteria"]["durations"] = [{"min":duration.split("-")[0], "max":duration.split("-")[1]}]
                deduped_results, _ = doSearchRequest(searchRequestData)

                natureSounds |= deduped_results
            searchRequestData["criteria"]["durations"] = None
            for continent in (pbar_duration := tqdm(filters["continent"]["values"], leave=False)):
                pbar_duration.set_description(" "*4*2 + f"continent: {continent}")
                
                searchRequestData["criteria"]["categories"] = [continent]
                deduped_results, _ = doSearchRequest(searchRequestData)

                natureSounds |= deduped_results
            category_total_sounds = len(natureSounds)
            allSounds |= natureSounds

        # Do a sanity check to make sure we got the correct number of sounds for our given category:
        # As mentioned in the README, this is sadly expected. we get a "good enough" amount though
        if category_total_sounds != filters["category"]["values"][category]:
            tqdm.write(f"WARNING: missing sounds in {category}! Expected {filters['category']['values'][category]} but only got {category_total_sounds}")
            sleep(2)

    # Dump local DB to file if we have debug settings set
    if USE_PICKEL_SEARCH_DB:
        with open('allSounds.pkl', 'wb') as file:
            pickle.dump(allSounds, file)


if __name__ == "__main__":
    # Container to hold the search scraping results
    allSounds = set()

    if not USE_PICKEL_SEARCH_DB or not os.path.isfile("./allSounds.pkl"):
        totalSoundCount = getTotalSoundCount()
        buildSearchFilters()
        filterChoiceString = '\n\t'.join(list(filters['category']['values'].keys()))
        selected_catagories = input(f"Would you like to download a subset of catagories? valid choices are 'all', or a comma seperated list of values from the following choices:\n\t{filterChoiceString}\n")
        if selected_catagories != "all":
            selected_catagories = set(selected_catagories.split(", "))
            if err := selected_catagories - set(filters['category']['values']):
                print(f"Error! invalid input: {err}")
                exit()
            else:
                for category in list(filters["category"]["values"].keys()):
                    if category not in selected_catagories:
                        del filters["category"]["values"][category]

        scrapeBBCSearchAPI(allSounds)
        # Check how close we got to the expected count:
        if selected_catagories == "all":
            if len(allSounds) != totalSoundCount:
                print(f"Warning: Missing sounds! expected {totalSoundCount} but only got {len(allSounds)}")
            else:
                print("All sounds scraped sucessfully. Ready to download...")
        else:
            if len(allSounds) < sum(filters["category"]["values"].values()): # If you thought you could just use this sum instead of hitting the API to get the sound count... think again! If you sum all the catagories, you get more than the total the API gives. Probably duplicates?
                print(f"Warning: Missing sounds! expected {sum(filters['category']['values'].values())} but only got {len(allSounds)}")
            else:
                print("All sounds scraped sucessfully. Ready to download...")

    else:
        with open('allSounds.pkl', 'rb') as file:
            allSounds = pickle.load(file)

    # ok, on to the downloading... finally! (just kidding... there are corrupt files that have no size / can't be downloaded!)
    problem_sounds = [sound for sound in allSounds if "wavFileSize" not in sound["fileSizes"]]
    for problem_sound in problem_sounds:
        allSounds.remove(problem_sound)

    # ok, NOW on to the downloading (can you tell im tired of this project yet?)
    total_download_size_mp3 = sum([int(sound["fileSizes"]["mp3FileSize"]) for sound in allSounds])
    total_download_size_wav = sum([int(sound["fileSizes"]["wavFileSize"]) for sound in allSounds])


    file_format = input(f"Would you like wav (raw), mp3 (lossy compression), or flac (lossless compression, will take longer and make your CPU scream)?\n" \
                        f"\twav size: {humanize.naturalsize(total_download_size_wav, binary=True)}\n" \
                        f"\tmp3 size:{humanize.naturalsize(total_download_size_mp3, binary=True)}\n" \
                        f"\taprox flac size:{humanize.naturalsize(total_download_size_wav * 0.55, binary=True)}\n")
    while file_format not in ["flac", "wav", "mp3"]:
        file_format = input("invalid input... try again, you must input one of the following: [flac, wav, mp3]. If the sizes scare you, press ctrl+c :p\n")

    outputLocationOK = False
    outputLocation = None
    while not outputLocationOK:
        outputLocation = input("Enter a file path to download files to:\n")
        if not os.path.exists(outputLocation) and not os.path.isdir(outputLocation):
            print("Your output path either does not exist, or is not a directory. try again!")
            continue
        if os.listdir(outputLocation):
            print(f"Warning! the file path entered is not empty! we are about to dump {len(allSounds)} into it! you probably don't want to do this")
            userConf = input("Are you sure you want to continue? [yes/no]: ")
            if userConf.lower() == "yes":
                outputLocationOK = True
        else:
            outputLocationOK = True

    if file_format == "flac":
        # Make a tmp folder for our wav file downloads
        os.mkdir(os.path.join(outputLocation, "_tmp"))

    with tqdm(total=len(allSounds)) as progressBar:
        with ThreadPoolExecutor() as thread_pool:
            futures = [thread_pool.submit(doFileDownload, soundInfo, outputLocation, file_format) for soundInfo in allSounds]
            for future in as_completed(futures):
                progressBar.update(1)

    if file_format == "flac":
        # Clean up our tmp folder
        os.removedirs(os.path.join(outputLocation, "_tmp"))

    buildSoundDBConf = input("Would you like to build a sound library for Davinci Resolve? [yes/no]: ")
    while buildSoundDBConf not in ["yes", "no"]:
        print(f"Invalid input {buildSoundDBConf}!")
        buildSoundDBConf = input("Would you like to build a sound library for Davinci Resolve? [yes/no]: ")
    
    if buildSoundDBConf == "yes":
        buildDavinciSoundLibraryDB(allSounds)
        print("Modifying Davinci Resolve sound database complete!")

    print("Thanks for checking out my goofy project, happy editing! (or happy listening to bird sounds, I don't judge)")

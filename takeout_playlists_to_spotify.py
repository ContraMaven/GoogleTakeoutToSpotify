import csv
import glob
import time
import os
import logging
import re

import json
import html
import requests

from datetime import datetime
from functools import wraps

"""Script to import Google Takeout of multiple Play Music playlists into 
new Spotify playlists.  Has not been tested with YouTube music Takeout.

Note that Google Takeout places each track in a separate CSV file, but 
this script can also handle multiple tracks per file.  Also, Google 
Takeout uses some HTML encoding, which this script will decode as needed.

You will need to register as a developer at 
https://developer.spotify.com/ to get the following:
- CLIENT_ID
- CLIENT_SECRET

I ran the following project to retrieve my USER_ID and auth TOKEN 
(ensure scope includes playlist-modify-private):
https://github.com/Erwan31/web-api-auth-examples-master

There are many other possibilities, see the developer guide for more:
https://developer.spotify.com/documentation/general/guides/authorization-guide/

"""

SEARCH = "https://api.spotify.com/v1/search"

"""If a search fails to find a match, this option will clean up search 
strings to improve the odds of a match and try again.

It removes:
- text in brackets
- forward slash and text that follows
- hyphen+space and text that follows
- the word "feat." and text that follows

e.g. {"artist": "Queen/David Bowie", 
        "album": "Hot Space - Deluxe Remastered Version", 
        "track": "Under Pressure feat. David Bowie (Remastered 2011)"}
    ->
    {"artist": "Queen", 
        "album": "Hot Space", 
        "track": "Under Pressure"}
"""
TRY_SIMPLIFIED_SEARCH = True

MAX_RETRIES = 3
RETRY_SLEEP_SEC = 5

# You will need to register as a developer at 
# https://developer.spotify.com/ to receive the following
CLIENT_ID = "XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX"
CLIENT_SECRET = "XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX"

USER_ID = "XXXXXXXXXXXXXXXXXXXXXXXXX" # Spotify User ID
PLAYLIST = str.format("https://api.spotify.com/v1/users/{0}/playlists", USER_ID)

# AUTH = "Bearer xxxxxxxx" # Replace with valid OAUTH token
TOKEN = "BQAoUVyJGatkAtE-fIBR2WpGdbdgF-7ktXO_aMGf_xlBiUOxflGbp9vtqyecqdLqjdMG1NRsTKjOLBAT_oTfFhvZy0yJusGw2BdcObdgODb8ignV-pHi6eMvxgc-JNLntHcjI2zQVR2AdH_JZ4vhH-vvtzpWzSL1pBrAZE-EdZcZe1aDRsQ-fNmjedvKB48H322Qo6qqhvJLhvy_"
AUTH = "Bearer " + TOKEN

# "Playlists" directory from the extracted takeout.zip
TAKEOUT_PLAYLISTS = "../Takeout/Google Play Music/Playlists"


logger = logging.getLogger()
logger.setLevel(logging.DEBUG)

formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

fh = logging.FileHandler('{:%Y-%m-%d}.log'.format(datetime.now()))
fh.setLevel(logging.INFO)
fh.setFormatter(formatter)
logger.addHandler(fh)

ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)
ch.setFormatter(formatter)
logger.addHandler(ch)


def simplify_search_field(str):
    simplified = re.sub(r'\(.*\)', '', str) # brackets
    simplified = re.sub(r'/.*', '', simplified) # slash
    simplified = re.sub(r'-\s+.*', '', simplified) # hyphen+space
    simplified = re.sub(r'feat\..*', '', simplified) # feat.

    return simplified.strip()


def simplify_track_info(track_info):
    """Simplifies all track_info dict fields in-place
    """
    track_info['artist'] = simplify_search_field(track_info['artist'])
    track_info['album'] = simplify_search_field(track_info['album'])
    track_info['track'] = simplify_search_field(track_info['track'])


def connection_error_retry(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        connection_error_retries = MAX_RETRIES
        while connection_error_retries > 0:
            try:
                return f(*args, **kwargs)
            except (
                    requests.exceptions.ConnectionError, 
                    requests.exceptions.RequestException,
                    requests.exceptions.HTTPError, 
                    requests.exceptions.Timeout
                    ) as connEx:
                connection_error_retries -= 1
                logger.error(str.format(
                    "Encountered exception ({0} retries remaining):", 
                    connection_error_retries
                    ))
                logger.error(connEx)
                if connection_error_retries > 0:
                    time.sleep(RETRY_SLEEP_SEC)
                else:
                    exit(1)
            except Exception as ex:
                logger.critical("Exiting due to unhandled exception:")
                logger.critical(ex)
                exit(1)

    return decorated


@connection_error_retry
def create_playlist(playlist_name):
    r = requests.post(
        PLAYLIST, 
        headers={'Authorization': AUTH, 'Content-Type': 'application/json'},
        json={'name': '{0}'.format(playlist_name), 'public': 'false'}
        )

    json_data = r.json()

    if 'error' in json_data:
        raise Exception(str(json_data['error']))

    if json_data['id']:
        return json_data['id']
    else:
        raise Exception("No playlist id found in json: " + json_data)


@connection_error_retry
def post_to_playlist(playlist_ID, track_URI):
    r = requests.post(
        str.format("https://api.spotify.com/v1/users/{0}/playlists/{1}/tracks", 
                USER_ID, playlist_ID),
        headers={'Authorization': AUTH},
        params={'uris': track_URI}
        )
    if r.status_code != 201:
        raise Exception(r)


def extract_track_URI(json_data):
    if 'error' in json_data:
        raise Exception(str(json_data['error']))

    if json_data['tracks']['items']:
        return json_data['tracks']['items'][0]['uri']
    else:
        return ""


@connection_error_retry
def search_album_and_artist(track_info):
    r = requests.get(
        SEARCH,
        headers={'Authorization': AUTH},
        params={'type': 'track',
                'q': 'artist:"{artist}" album:"{album}" track:"{track}"'.format(**track_info)}
        )
    return extract_track_URI(r.json())


@connection_error_retry
def search_album(track_info):
    r = requests.get(
        SEARCH,
        headers={'Authorization': AUTH},
        params={'type': 'track',
                'q': 'album:"{album}" track:"{track}"'.format(**track_info)}
        )
    return extract_track_URI(r.json())


@connection_error_retry
def search_artist(track_info):
    r = requests.get(
        SEARCH,
        headers={'Authorization': AUTH},
        params={'type': 'track',
                'q': 'artist:"{artist}" track:"{track}"'.format(**track_info)})
    return extract_track_URI(r.json())


def get_track_list(tracks_dir):
    track_list = []
    incomplete_track_list = []

    for csv_filename in glob.glob(tracks_dir + os.path.sep + "*.csv"):
        logger.debug("Reading " + csv_filename)

        with open(csv_filename, encoding="utf-8") as csv_file:
            reader = csv.DictReader(csv_file)
            
            for row in reader:
                # Google Takeout uses HTML encoding for the following
                # fields - decode it
                artist = html.unescape(row['Artist'])
                album = html.unescape(row['Album'])
                track = html.unescape(row['Title'])
                track_dict = {'artist': artist, 'album': album, 'track': track}
                logger.debug(track_dict)

                if not track or (not artist and not album):
                    incomplete_CSV = os.path.basename(csv_filename)
                    incomplete_track_list.append(incomplete_CSV)
                    logger.debug("Skipping track due to missing details: " 
                                + incomplete_CSV)
                else:
                    track_list.append(track_dict)
    
    logger.info(str.format("Found {0} tracks", len(track_list)))

    return track_list, incomplete_track_list


def get_playlists_dict(playlist_top_level_dir):
    """Returns two dictionaries:
        - playlists with complete track info
        - playlists with incomplete track info
    """
    playlists_dict = {}
    incomplete_playlists_dict = {}
    
    for playlist_dir in glob.glob(playlist_top_level_dir + os.path.sep + "*"):
        if os.path.isdir(playlist_dir):
            logger.info("Reading " + playlist_dir)
        else:
            logger.info("Skipping file " + playlist_dir)
            next

        playlist_name = os.path.basename(playlist_dir)

        tracks_dir = playlist_dir + os.path.sep + "Tracks"
        if os.path.exists(tracks_dir) and os.path.isdir(tracks_dir):
            logger.debug("Found Tracks dir")
        else:
            tracks_dir = playlist_dir

        tracks, incomplete_tracks = get_track_list(tracks_dir)

        if (tracks):
            playlists_dict[playlist_name] = {}
            playlists_dict[playlist_name]['tracks'] = tracks

        if incomplete_tracks:
            incomplete_playlists_dict[playlist_name] = {}
            incomplete_playlists_dict[playlist_name]['tracks'] = incomplete_tracks
    
    return playlists_dict, incomplete_playlists_dict


def get_track_URI(track):
    track_URI = search_album_and_artist(track)

    if not track_URI and TRY_SIMPLIFIED_SEARCH:
        simplify_track_info(track)
        logger.warn(
            "\tTrying simplified search: {artist}/{track}/{album}".format(**track)
            )   
        track_URI = search_album_and_artist(track)

    if not track_URI:
        logger.warn(
            "\tTrying Track/Album search: {track}/{album}".format(**track)
            )
        track_URI = search_album(track)

        if not track_URI:
            logger.warn(
                "\tTrying Track/Artist search: {track}/{artist}".format(**track)
                )
            track_URI = search_artist(track)
    
    return track_URI


logger.info(str.format(
    "STARTING EXECUTION.  Google Takeout Playlists directory: {0}", 
    TAKEOUT_PLAYLISTS
    ))

playlists, incomplete_playlists = get_playlists_dict(TAKEOUT_PLAYLISTS)

if incomplete_playlists:
    logger.warn(str.format(
        "Some playlists contained incomplete track information: \n{0}", 
        json.dumps(incomplete_playlists, default=str, indent=4, sort_keys=True)
        ))

for playlist_name, playlist_details in playlists.items():
    logger.info("Creating playlist " + playlist_name)
    missing_tracks = False

    if not playlist_details['tracks']:
        logger.warn("No track information found, skipping playlist " + playlist_name)
        next

    playlist_ID = create_playlist(playlist_name)
    playlists[playlist_name]['id'] = playlist_ID

    for track in playlist_details['tracks']:
        track_URI = get_track_URI(track)
        track['uri'] = track_URI
        
        if track_URI:
            logger.debug("     Found " + track_URI)
            post_to_playlist(playlist_ID, track_URI)
        else:
            missing_tracks = True
    
    if missing_tracks:
        logger.error("Unable to find the following tracks for playlist " + playlist_name)
        for track in playlist_details['tracks']:
            if not track['uri']:
                logger.error(json.dumps(track))
    else:
        logger.info("All tracks were found!")

exit(0)
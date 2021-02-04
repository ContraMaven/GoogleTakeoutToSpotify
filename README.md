# GoogleTakeoutToSpotify

Script to import Google Takeout of multiple Play Music playlists into 
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

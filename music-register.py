from __future__ import print_function
import ctypes
from datetime import datetime
from pathlib import Path
import time
import os.path
import psutil

musicListFile = Path(__file__).parent.resolve().__str__() + r"\music-list.csv"
musicUniqueFile = Path(__file__).parent.resolve().__str__() + r"\musics.csv"
timeSleep = 1

def getProcessTitles(): 
    EnumWindows = ctypes.windll.user32.EnumWindows
    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int))
    GetWindowText = ctypes.windll.user32.GetWindowTextW
    GetWindowTextLength = ctypes.windll.user32.GetWindowTextLengthW
    IsWindowVisible = ctypes.windll.user32.IsWindowVisible
    GetWindowThreadProcessId = ctypes.windll.user32.GetWindowThreadProcessId

    results = []
    
    def foreach_window(hwnd, lParam):
        if IsWindowVisible(hwnd):
            length = GetWindowTextLength(hwnd)
            buff = ctypes.create_unicode_buffer(length + 1)
            GetWindowText(hwnd, buff, length + 1)
            title = buff.value
            
            pid = ctypes.c_ulong()
            GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            
            try:
                process = psutil.Process(pid.value)
                exe = process.exe()
                results.append((title, exe))
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                results.append((title, None))
                
        return True

    EnumWindows(EnumWindowsProc(foreach_window), 0)
    return results

def getSpotifyTitle():
    exesTitles = getProcessTitles()
    for title, exe in exesTitles:
        if (exe.split("\\")[-1] == "Spotify.exe"):
            if (title != "None"):
                return title
    return None

def saveMusic(artist, music, secondsListen, date, hour):
    try:
        with open(musicListFile, "a", encoding="utf-8") as f:
            f.write(f"{artist};{music};{secondsListen};{date};{hour}\n")
    except:
        print("Error saving music in file", musicListFile)
    
    try:
        if not isMusicRegistered(artist, music):
            with open(musicUniqueFile, "a", encoding="utf-8") as f:
                f.write(f"{artist};{music}\n")
    except:
        print("Error saving unique music in file", musicUniqueFile)

def isMusicRegistered(artist, music):
    if not os.path.exists(musicUniqueFile):
        return False
    try:
        with open(musicUniqueFile, "r", encoding="utf-8") as f:
            for line in f:
                registered_artist, registered_music = line.strip().split(";")
                if registered_artist == artist and registered_music == music:
                    return True
    except:
        print("Error reading unique music file", musicUniqueFile)
    return False

previousArtist = ""
previousMusic = ""
previousDate = None
previousHour = None
musicStart = None
pauseTime = 0

while True:
    processTitle = getSpotifyTitle()

    if processTitle is None:
        musicStart = None
        pauseTime = 0
        continue

    if processTitle == "Spotify":
        pauseTime += timeSleep
        time.sleep(timeSleep)
        continue

    titleDivided = processTitle.split(" - ")

    if len(titleDivided) == 2:
        artist, music = titleDivided
    elif len(titleDivided) > 2:
        artist = titleDivided[0]
        music = " - ".join(titleDivided[1:])
    else:
        artist = None
        music = None

    if (artist != None and music != None):
        if not (artist == previousArtist and music == previousMusic):
            if musicStart is not None:
                secondsListened = int(time.time() - musicStart - pauseTime)
                if previousArtist and previousMusic:
                    saveMusic(previousArtist, previousMusic, secondsListened, previousDate, previousHour)

            previousArtist = artist
            previousMusic = music
            previousDate = datetime.today().strftime('%d-%m-%Y')
            previousHour = datetime.today().strftime("%H:%M:%S")
            musicStart = time.time()
            pauseTime = 0
            print("Artist: " + artist)
            print("Music: " + music)
            print("-" * 40)
    time.sleep(timeSleep)
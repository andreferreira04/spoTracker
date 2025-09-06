# SpoTracker

## How to Configure SpoTracker to Run at Startup

Follow these steps to set up SpoTracker so that it runs automatically when your computer starts:

---

### Steps for Configuration on Windows:
1. **Install the .exe from GitHub Releases:**
   - Windows Defender may exclude the file due to suspected virus

1. **Locate the Startup Folder:**
   - Press `Win + R` to open the "Run" dialog box.
   - Type `shell:startup` and press Enter. This will open the Startup folder.

2. **Create a Shortcut for the Script:**
   - Add a shortcut to the SpoTracker.exe file

---

### First-Time Execution
- The first time you start your PC, you might be prompted with a dialog asking for confirmation to execute the script.  
  Select **"Don't ask again"** and click **Yes** to allow the script to run automatically.

---

### Data stored
- All the stored data can be found on `C:\Users\your-user\Documents\SpoTracker`

---

### Verifying the Script is Running
- Open **Task Manager** (`Ctrl + Shift + Esc`).
- Look for a running process named **SpoTracker**. This confirms that the script is active.

---

### Additional Notes
- If you need to stop the script temporarily, end the process via Task Manager.

With these steps completed, SpoTracker will run seamlessly whenever your computer starts.

## For developers

### Generate .exe from .py

Run `pyinstaller --noconsole  music-register.py`
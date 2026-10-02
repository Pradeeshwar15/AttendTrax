# 📱 AttendTrax – Android Studio Project

This directory contains the complete native **Android Studio Project** for AttendTrax.

---

## 🚀 How to Open and Run in Android Studio

### Step 1: Open in Android Studio
1. Open **Android Studio**.
2. Click **File** &rarr; **Open...** (or click *Open* on the Welcome Screen).
3. Select the `android/` directory inside this repository:
   ```
   c:\Users\prade\OneDrive\Desktop\Cur Dev\android
   ```
4. Click **OK**. Android Studio will automatically sync the Gradle files and build the project index.

---

### Step 2: Run on Emulator or Physical Phone
1. Connect an Android phone via USB (with *USB Debugging* enabled in Developer Options) **OR** start an Android Virtual Device (AVD Emulator).
2. Click the green **Run (▶)** button in the top toolbar of Android Studio (or press `Shift + F10`).
3. The AttendTrax app will install and launch instantly with hardware acceleration.

---

### Step 3: Generate APK for Direct Installation
To create a standalone APK that can be shared or installed directly on any phone:
1. In Android Studio, go to the top menu: **Build** &rarr; **Build Bundle(s) / APK(s)** &rarr; **Build APK(s)**.
2. When the build finishes, click the **"locate"** link in the popup notification at the bottom right.
3. Your APK will be located at:
   ```
   android/app/build/outputs/apk/debug/app-debug.apk
   ```

---

## ✨ Features Built into the Android App
- **Hardware-Accelerated WebView**: Smooth 60 FPS transitions and micro-animations.
- **DomStorage & Persistent Sessions**: LocalStorage and cookies are preserved across app restarts so you stay logged in.
- **Pull to Refresh (`SwipeRefreshLayout`)**: Swipe down anywhere to reload attendance rosters or analytics.
- **Top Loading Progress Bar**: Sleek gradient progress indicator during page navigation.
- **Native File Chooser**: Fully supports selecting Excel (.xlsx) and CSV files for the Admin Bulk Setup feature.
- **Smart Back Navigation**: Back button navigates through portals and tabs; double-tap back to safely exit the app.
- **Offline Fallback Screen**: Gracefully shows a "No Internet" screen with a one-tap *Retry Connection* button if network drops.

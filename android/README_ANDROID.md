# AttendTrax Android Application

Native Android wrapper for AttendTrax with hardware-accelerated WebView, pull-to-refresh, download management, and session persistence.

## Project Structure

```
android/
├── build.gradle                 # Project-level Gradle build configuration
├── settings.gradle              # Module includes and repository definitions
├── gradle.properties            # JVM & AndroidX build properties
└── app/
    ├── build.gradle             # App-level build file (compileSdk 34, minSdk 24)
    └── src/main/
        ├── AndroidManifest.xml  # Permissions, themes, Activity definitions
        ├── java/com/attendtrax/app/
        │   └── MainActivity.java# WebView controller, DownloadListener, Back navigation
        └── res/
            ├── layout/activity_main.xml     # Fullscreen WebView + SwipeRefresh + Offline screen
            ├── values/                      # Colors, strings, themes
            ├── drawable/                    # Vector icons & progress bar drawables
            └── mipmap-anydpi-v26/           # Adaptive launcher icons
```

## How to Open and Run in Android Studio

1. **Launch Android Studio**.
2. Click **Open** (or `File > Open...`).
3. Browse to and select the `android` folder located at:
   ```
   c:\Users\prade\OneDrive\Desktop\Cur Dev\android
   ```
4. Allow Gradle to sync and download necessary dependencies.
5. Connect your Android device via USB (with USB Debugging enabled) or start an Android Virtual Device (AVD).
6. Click the green **Run** ▶️ button (or press `Shift + F10`).

## Generating a Standalone APK (for installing directly on phones)

1. In Android Studio, go to the top menu: **Build > Build Bundle(s) / APK(s) > Build APK(s)**.
2. Once the build finishes, click the **locate** popup link to find your `app-debug.apk`.
3. Transfer `app-debug.apk` to any Android phone and install it.

## Key Features

- **DOM Storage & Session Retention**: User sessions remain active even when the app is closed.
- **Pull to Refresh**: Drag down from the top to refresh attendance rosters and analytics.
- **CSV Report Exports**: Downloads attendance CSV spreadsheets directly into Android's native `Download/` folder.
- **Offline Screen**: Displays a network troubleshooting screen if there is no internet connection, with an instant retry button.
- **Safe Back Navigation**: Navigates between screens instead of abruptly exiting the app.

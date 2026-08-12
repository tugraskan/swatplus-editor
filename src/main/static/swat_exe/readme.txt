By default, we ship SWAT+ Editor with the official stable release.

If you would like to provide your own SWAT+ model version, you may copy your executable files into this folder, then open the exe-options.csv file and add a new row with the description and file name of your custom executable.

Caution: providing your own executables may cause errors if it is not compatible with the editor's default official release version. 
Changes in input or output file formats between model versions may cause errors.

--------------------------------------
Running the Model Outside SWAT+ Editor
--------------------------------------

If you have a static build (single executable file), you have two options:

Option 1: Copy the executable

1. Copy the executable file into your TxtInOut directory
2. Open a terminal in that directory
3. Run the executable

Option 2: Run from original location

1. Open a command prompt
2. Navigate to your TxtInOut folder: 

    cd "C:\My-Project\Scenarios\Default\TxtInOut"

3. Run the SWAT executable with its full path:

    "C:\Users\{YOUR_USERNAME}\SWATPlus\SWATPlusEditor\resources\app.asar.unpacked\static\swat_exe\{EXE_FILENAME_TO_RUN}.exe"

Note: Replace {YOUR_USERNAME} and {EXE_FILENAME} with your actual username and the correct executable name.
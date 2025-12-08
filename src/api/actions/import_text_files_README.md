# Import Text Files to SQLite Database

## Overview

The `import_text_files` action allows you to import existing SWAT+ text files from a TxtInOut directory into a project SQLite database. This is useful when you have:
- An existing SWAT+ project with text files but no SQLite database
- Text files from another source that you want to import into the SWAT+ Editor
- A need to recreate the database from a backup of text files

## Usage

### Command Line

```bash
python swatplus_api.py import_text_files \
  --project_db_file /path/to/project.sqlite \
  --txtinout_dir /path/to/TxtInOut \
  --editor_version 3.0.0 \
  --swat_version 60.5.4
```

### Parameters

- `project_db_file` (required): Full path to the project SQLite database file
  - If the file doesn't exist, you should create it first using the `create_database` action
- `txtinout_dir` (required): Full path to the TxtInOut directory containing SWAT+ text files
- `editor_version` (optional): Editor version string (default: "3.0.0")
- `swat_version` (optional): SWAT+ version string (default: "60.5.4")

## Prerequisites

1. **Create an empty project database** if one doesn't exist:
   ```bash
   python swatplus_api.py create_database \
     --db_type project \
     --db_file /path/to/project.sqlite \
     --db_file2 /path/to/datasets.sqlite \
     --project_name "MyProject" \
     --editor_version 3.0.0
   ```

2. **Ensure TxtInOut directory exists** and contains valid SWAT+ text files

## File Import Order

The import process reads files in a specific order to satisfy database foreign key dependencies:

1. Simulation configuration (time.sim, print.prt, object.prt)
2. Climate/weather files (weather-sta.cli, weather-wgn.cli)
3. Parameter database files (plants.plt, fertilizer.frt, tillage.til, etc.)
4. Soil files (soils_lte.sol, nutrients.sol)
5. Decision tables (lum.dtl, res_rel.dtl, etc.)
6. Connection files (hru.con, channel.con, etc.)
7. Channel files (channel.cha, hydrology.cha, etc.)
8. Reservoir files (reservoir.res, hydrology.res, etc.)
9. Routing unit files (rout_unit.rtu, rout_unit.ele)
10. Aquifer files (aquifer.aqu, initial.aqu)
11. HRU files (hru-data.hru, hru-lte.hru)
12. Hydrology files (hydrology.hyd, topography.hyd, field.fld)
13. Initialization files (plant.ini, soil_plant.ini, etc.)
14. Land use management files (landuse.lum, management.sch, etc.)
15. Operations files (harv.ops, graze.ops, etc.)
16. Recall files (recall.rec)
17. Basin files (codes.bsn, parameters.bsn)
18. Change/calibration files (calibration.cal, cal_parms.cal)
19. Regions files (ls_unit.def, ls_unit.ele)

## Current Limitations

Many SWAT+ text file types currently have `read()` methods that are not yet implemented. The import process:
- Gracefully handles files without read implementations (catches NotImplementedError)
- Imports files that have working read implementations (e.g., soils_lte.sol)
- Can be extended by implementing read() methods in the respective fileio classes

## Implementation Status

### Files with Working Read Implementations
- `soils_lte.sol` - LTE soil data

### Files Needing Read Implementation
Most other file types currently raise NotImplementedError when read() is called. These can be implemented as needed by:
1. Opening the respective file in `/src/api/fileio/`
2. Implementing the `read()` method using `read_default_table()` or custom parsing logic
3. Following the pattern used in working implementations

## Example Workflow

```bash
# 1. Create a new project database
python swatplus_api.py create_database \
  --db_type project \
  --db_file /home/user/projects/myproject.sqlite \
  --db_file2 /home/user/swatplus_datasets.sqlite \
  --project_name "MyProject" \
  --editor_version 3.0.0

# 2. Import text files from TxtInOut directory
python swatplus_api.py import_text_files \
  --project_db_file /home/user/projects/myproject.sqlite \
  --txtinout_dir /home/user/projects/TxtInOut \
  --editor_version 3.0.0 \
  --swat_version 60.5.4

# 3. Use the populated database in SWAT+ Editor or export data
python swatplus_api.py export_csv table_name myproject.sqlite ...
```

## Error Handling

The import process will:
- Check if the TxtInOut directory exists before starting
- Check if each individual file exists before attempting to read it
- Gracefully skip files that don't have read implementations
- Display progress messages during import
- Report any errors that occur during the import process

## Future Enhancements

To fully support all SWAT+ file types, additional read() implementations are needed. The framework is in place and individual file types can be added incrementally based on user needs.

## Related Actions

- `create_database`: Create a new project database
- `write_files`: Write SQLite database data to text files (opposite operation)
- `import_csv`: Import CSV data into specific tables
- `export_csv`: Export table data to CSV

## Support

For issues or questions:
1. Check that your TxtInOut directory contains valid SWAT+ text files
2. Verify the project database was created successfully
3. Check the console output for specific error messages
4. Refer to SWAT+ documentation for file format specifications

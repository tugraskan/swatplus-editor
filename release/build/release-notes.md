### SWAT+ Editor 4.0.2 ###

* Bug fix affecting gfortran compiling: print plants.plt days_mat and yrs_mat as integer instead of decimals.
* Work-around fix affecting instances where the model has an error exit code despite the model running successfully.
* **IMPORTANT:** Time-series recall (point source/inlet) data is still not supported in this release. Please keep using version 3.2.x and do not upgrade yet if you need recall.

### SWAT+ Editor 4.0.1 ###

* Bug fix related to codes_bsn/i_fpwet column name change giving an error on new project setups using an old swatplus_datasets.sqlite version.

### SWAT+ Editor 4.0.0 ###
**IMPORTANT:** This new version of the editor is only compatible with SWAT+ rev. 62 and later. Due to structural model changes, rev. 61 and earlier are NOT supported. Project updates are available after software update.

**RECALL NOT SUPPORTED:** If you are using time-series recall (point source/inlet) data, we encourage you to not update your software yet. Continue using the 3.2.x versions with SWAT+ rev. 61.0.2. Recall is moving to water allocation and is not yet ready in this release of the model. We expect it to be ready late summer 2026.

* Compatible with SWAT+ rev. 62
* gwflow structure updates (QSWAT+ v4.0 update is REQUIRED)
* Add carbon module (see basin section for carbon and carbon layers)
* Update print.prt to include gwflow options and legacy carbon options
* Time-series recall DISABLED (see note above)

_Several breaking changes from v3.x. This version is NOT backwards compatible._
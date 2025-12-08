#!/usr/bin/env python
"""
Example script demonstrating how to use the import_text_files action
to recreate a SQLite database from SWAT+ text files.

This script shows the complete workflow:
1. Create a new project database
2. Import text files from a TxtInOut directory
3. Verify the import was successful
"""

import sys
import os
import argparse
import sqlite3
import subprocess
from pathlib import Path


def create_example_database(project_db, datasets_db):
	"""Create an example project database."""
	print("Creating project database...")
	cmd = [
		"python", "swatplus_api.py", "create_database",
		"--db_type", "project",
		"--db_file", project_db,
		"--db_file2", datasets_db,
		"--project_name", "Example Import Project",
		"--editor_version", "3.0.0"
	]
	
	result = subprocess.run(cmd, capture_output=True, text=True)
	if result.returncode != 0:
		print(f"Error creating database: {result.stderr}")
		return False
	
	print("✓ Project database created successfully")
	return True


def import_text_files(project_db, txtinout_dir):
	"""Import text files from TxtInOut directory."""
	print(f"\nImporting text files from {txtinout_dir}...")
	cmd = [
		"python", "swatplus_api.py", "import_text_files",
		"--project_db_file", project_db,
		"--txtinout_dir", txtinout_dir,
		"--editor_version", "3.0.0",
		"--swat_version", "60.5.4"
	]
	
	result = subprocess.run(cmd, capture_output=True, text=True)
	if result.returncode != 0:
		print(f"Error importing text files: {result.stderr}")
		return False
	
	print("✓ Text files imported successfully")
	return True


def verify_import(project_db):
	"""Verify that data was imported into the database."""
	print(f"\nVerifying import...")
	
	if not os.path.exists(project_db):
		print(f"✗ Database file does not exist: {project_db}")
		return False
	
	try:
		conn = sqlite3.connect(project_db)
		cursor = conn.cursor()
		
		# Get list of tables
		cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
		tables = cursor.fetchall()
		
		print(f"✓ Database contains {len(tables)} tables")
		
		# Check a few key tables for data
		key_tables = ['project_config', 'soils_lte_sol']
		for table_name in key_tables:
			cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
			count = cursor.fetchone()[0]
			if count > 0:
				print(f"  - {table_name}: {count} rows")
			else:
				print(f"  - {table_name}: empty")
		
		conn.close()
		return True
		
	except Exception as e:
		print(f"✗ Error verifying database: {e}")
		return False


def main():
	parser = argparse.ArgumentParser(
		description="Example: Import SWAT+ text files to SQLite database",
		formatter_class=argparse.RawDescriptionHelpFormatter,
		epilog="""
Examples:
  # Basic usage with existing datasets database
  python example_import_text_files.py /path/to/TxtInOut /path/to/datasets.sqlite
  
  # Specify custom output location
  python example_import_text_files.py /path/to/TxtInOut /path/to/datasets.sqlite -o /path/to/output.sqlite
		"""
	)
	
	parser.add_argument('txtinout_dir', help='Path to TxtInOut directory containing SWAT+ text files')
	parser.add_argument('datasets_db', help='Path to existing datasets SQLite database')
	parser.add_argument('-o', '--output', help='Path for output project database (default: project_import.sqlite)',
						default='project_import.sqlite')
	
	args = parser.parse_args()
	
	# Validate inputs
	if not os.path.exists(args.txtinout_dir):
		print(f"Error: TxtInOut directory does not exist: {args.txtinout_dir}")
		return 1
	
	if not os.path.exists(args.datasets_db):
		print(f"Error: Datasets database does not exist: {args.datasets_db}")
		print("You need a datasets database file. You can create one with:")
		print("  python swatplus_api.py create_database --db_type datasets --db_file datasets.sqlite --editor_version 3.0.0")
		return 1
	
	# Make paths absolute
	txtinout_dir = os.path.abspath(args.txtinout_dir)
	datasets_db = os.path.abspath(args.datasets_db)
	project_db = os.path.abspath(args.output)
	
	print("=" * 60)
	print("SWAT+ Text Files Import Example")
	print("=" * 60)
	print(f"TxtInOut directory: {txtinout_dir}")
	print(f"Datasets database:  {datasets_db}")
	print(f"Output database:    {project_db}")
	print("=" * 60)
	
	# Step 1: Create database
	if not create_example_database(project_db, datasets_db):
		return 1
	
	# Step 2: Import text files
	if not import_text_files(project_db, txtinout_dir):
		return 1
	
	# Step 3: Verify
	if not verify_import(project_db):
		return 1
	
	print("\n" + "=" * 60)
	print("SUCCESS!")
	print("=" * 60)
	print(f"Your SWAT+ project database has been created: {project_db}")
	print("\nNext steps:")
	print("  - Open the database in SWAT+ Editor")
	print("  - Export data to CSV: python swatplus_api.py export_csv ...")
	print("  - Write files back to text format: python swatplus_api.py write_files ...")
	print("=" * 60)
	
	return 0


if __name__ == '__main__':
	sys.exit(main())

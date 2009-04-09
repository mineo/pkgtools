#!/usr/bin/env python
import sys
import os
import sqlite3
import tarfile
import re

def dbexec(database, statement, bindings):
  """Execute a statement, and close the cursor returned by database.execute.
  Useful for INSERT and DELETE, where we don't use the cursor."""
  cursor = database.execute(statement, bindings)
  cursor.close()

name_regex = '^(.+)'
ver_regex = '-([^-]+)'
rel_regex = '-([^-]+)$'
pkg_filename_regex = re.compile(name_regex + ver_regex + rel_regex)

def parse_pkg_filename(name):
  """Split a filename into (pkgname, pkgver, pkgrel).  Return None if the
  name is invalid."""
  matchdata = pkg_filename_regex.match(name)
  if matchdata == None:
    return None
  else:
    return (matchdata.group(1), matchdata.group(2), float(matchdata.group(3)))

def read_filelist(reponame, filename, fileobj, database):
  """Read a list of files, inserting them into the DB."""
  fileobj.readline() # Get rid of that %FILES% at the top of the file.
  # filename looks like repo/pkgname-pkgver-pkgrel/files
  try:
    filename = os.path.normpath(filename).split(os.path.sep)[-2]
  except IndexError:
    print >>sys.stderr, 'Ignoring file with malformed name %s.' % (filename,)
    return
  parsed_name = parse_pkg_filename(filename)
  if parsed_name == None:
    print >>sys.stderr, 'Ignoring file with malformed name %s.' % (filename,)
    return
  (pkgname, pkgver, pkgrel) = parsed_name

  cursor = database.execute(
    'SELECT version, release FROM versioned_packages WHERE reponame = ? AND packagename = ?', (pkgname, pkgver))
  pkgdata = cursor.fetchone()
  cursor.close()
  if pkgdata != None and pkgdata[0] == pkgver and pkgdata[1] == pkgrel:
    return # No work to do.

  try:
    dbexec(database, 'INSERT INTO packages VALUES (?)', (pkgname,))
  except sqlite3.IntegrityError:
    pass # Try to add pkgname to packages, keep going if it's already there.
  dbexec(database,
         'DELETE FROM versioned_packages WHERE reponame = ? AND packagename = ?',
         (reponame, pkgname))
  dbexec(database, 'DELETE FROM files WHERE reponame = ? AND packagename = ?',
         (reponame, pkgname))
  dbexec(database,
         ('INSERT INTO versioned_packages (reponame, packagename, version, release)'
          + 'VALUES (?, ?, ?, ?)'),
         (reponame, pkgname, pkgver, pkgrel))

  for line in fileobj.readlines():
    dbexec(database,
           ('INSERT INTO files (reponame, packagename, version, release, filename)'
            + ' VALUES (?, ?, ?, ?, ?)'),
           (reponame, pkgname, pkgver, pkgrel, line[0:-1]))

  database.commit()


def read_repodata(reponame, tarball, database):
  for entry in tarball:
    if not entry.isreg():
      continue
    member_file = tarball.extractfile(entry)
    read_filelist(reponame, entry.name, member_file, database)
    member_file.close()

if len(sys.argv) != 3:
  print >>sys.stderr, 'Usage: %s <DATABASE> <TARBALL>' % (sys.argv[0],)
  sys.exit(1)

tarpath = sys.argv[2]
reponame =  re.match('^([^.]+).files.tar.gz', os.path.split(tarpath)[-1])
if reponame == None:
  print >>sys.stderr, 'Error: the name of the tarball should have the form REPONAME.files.tar.gz.'
  sys.exit(1)
reponame = reponame.group(1)
tarball = tarfile.open(tarpath)
db = sqlite3.connect(sys.argv[1])
read_repodata(reponame, tarball, db)
db.close()
tarball.close()

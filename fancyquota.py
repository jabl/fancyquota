#!/usr/bin/python
# -*- coding: utf-8 -*-
# vim: set fileencoding=utf-8

"""
Copyright (c) 2008-2013 Janne Blomqvist

Permission is hereby granted, free of charge, to any person obtaining a copy of
this software and associated documentation files (the "Software"), to deal in
the Software without restriction, including without limitation the rights to
use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of
the Software, and to permit persons to whom the Software is furnished to do so,
subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS
FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR
COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER
IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
"""

"""Print out quota information.

This program tries to print out quota in a sensible way that works with the
automounter.  

Put the environment variables pointing to directories that must be visited into
the fs_env list. Alternatively, put the directories directly into the fs_dir
list.

"""

fs_env = ["HOME", "WRKDIR", "ARCHIVE"]
fs_dir = []

import os

def env_dirs():
    """Get a dict of directories:env pointed to by fs_env."""
    edirs = {}
    for env in fs_env:
        dir = os.getenv(env)
        if dir != None:
            edirs[dir] = env
    return edirs

def visit_fs():
    """Visit file systems to ensure they are mounted."""
    dirs = env_dirs().keys()
    [dirs.append(d) for d in fs_dir]
    for dir in dirs:
        try:
            os.stat(dir)
        except OSError:
            pass

def mp_env():
    """Return a dict of mountpoint:env_var pairs.
    
    Note that the visit_fs function should have been called before calling
    this function.
    
    """
    edirs = env_dirs()
    mp = {}
    for dir in edirs.keys():
	mpdir = dir
	while not os.path.ismount(mpdir):
	    mpdir = os.path.dirname(mpdir)
	mp[mpdir] = edirs[dir]
    return mp

def fs_env_map():
    """Return a dict of filesystem : env variable pairs."""
    edirs = mp_env()
    mp = {}
    f = open("/etc/mtab")
    lines = f.readlines()
    f.close()
    for line in lines:
        ls = line.split()
        if ls[1] in edirs:
	    mp[ls[0]] = edirs[ls[1]]
    for fscand in mp.keys():
	fspath = fscand
	while not os.path.ismount(fspath) and not fspath == '':
	    fspath = os.path.dirname(fspath)
	if fspath != '/':
	   # We probably found a bind mountpoint
	   for line in lines:
	       ls = line.split()
	       if ls[1] == fspath:
		   tmpval = mp[fscand]
		   del mp[fscand]
		   mp[ls[0]] = tmpval
    return mp

def map_fs(fs, mp):
    """Try to map the filesystem to one of the env variables."""
    for k in mp.keys():
        if k == fs:
            return mp[k]

    # Failed exact path match, try to match to path by chopping off a component
    # from the end and replacing it with the username. This should deal with
    # the automounter wildcard mounts hopefully without accidentally matching
    # incorrectly.

    fschop = os.path.dirname(fs)
    fsme = os.path.join(fschop, os.getenv("LOGNAME"))
    foundme = False
    for line in open("/etc/mtab"):
        ls = line.split()[0]
        if ls == fsme:
            foundme = True
    if foundme:
        if fsme in mp.keys():
            return mp[fsme]
        else:
            return fsme
    return fs

def print_quota(quota):
    """Pretty print quotas."""
    dlen = 12
    for ug in quota:
        for vals in ug[1].keys():
            td = len(vals) + 4
            if td > dlen:
                dlen = td
    first = True
    for ug in quota:
        fsq = ug[1]
        quotas = []
        for vals in fsq.values():
            quotas.append(int(vals[1]))
        if len(fsq) == 0 or True in [x < 2 for x in quotas]:
            continue
        if first:
            first = False
        else:
            print '-' * (dlen + 49)
        print 'Quota for ' + ug[0] + ' in units of GB'
        hfmt = "%-" + str(dlen) + "s %7s %10s %9s %9s %9s"
        print hfmt % ('Directory', 'Usage', 'Quota', '% used', 'Limit', 'Grace')
        for k in fsq.keys():
            use = fsq[k][0].replace('*', ' ')
            use = float(use)/1000**2
            q = float(fsq[k][1])/1000**2
            hq = float(fsq[k][2]) / 1000**2
            if (hq > q):
                grace = fsq[k][3]
            else:
                grace = ''
            pcent = use / q * 100
            fmt = "%-" + str(dlen) + "s %7.2f %10.2f %9.1f %9.2f %s"
            print fmt % (k, use, q, pcent, hq, grace)
    

def run_quota():
    """Run the quota command and parse output.
    
    Checks both user and group quotas. Ignores file limits, just number of
    bytes.
    
    """
    p = os.popen("/usr/bin/quota -ug")
    fs = ""
    mp = fs_env_map()
    myquota = []
    for line in p.readlines():
        if line.find("Disk quotas for") != -1:
            current = " ".join(line.split()[3:5])
            curlist = {}
            myquota.append((current, curlist))
        elif line.find("     Filesystem  blocks   quota   limit") == -1:
            ls = line.split()
            if len(ls) == 1:
                splitline = True
                fs = map_fs(ls[0], mp)
            elif splitline:
                curlist[fs] = (ls[0], ls[1], ls[2], ls[3])
                splitline = False
            else:
                curlist[map_fs(ls[0], mp)] = (ls[1], ls[2], ls[3], ls[4])
    p.close()
    print_quota(myquota)


def quota_main():
    """Main interface of the quota program."""
    from optparse import OptionParser
    usage = """%prog [options]

Print out disk quotas in a nice way, try to work with automounted 
file systems.
"""
    parser = OptionParser(usage, version="1.4")
    parser.add_option("-s", "--sensible-units", dest="sensible", \
            action="store_true", help="Use sensible units in output (default)")
    parser.parse_args()
    visit_fs()
    run_quota()


if __name__=="__main__":
    quota_main()


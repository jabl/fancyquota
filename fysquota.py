#!/usr/bin/python
# vim: set fileencoding=latin-1
# Copyright (c) 2008 Janne Blomqvist

#  This file is part of fysquota.

#  fysquota is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 3 of the License, or
#  (at your option) any later version.

#  fysquota is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.

#  You should have received a copy of the GNU General Public License
#  along with fysquota.  If not, see <http://www.gnu.org/licenses/>.

"""Print out quota information.

This program tries to print out quota in a sensible way that works with the
automounter.  

Put the environment variables pointing to directories that must be checked into
the fs_env list. Alternatively, put the directories directly into the fs_dir
list.

"""

fs_env = ["HOME", "WRKDIR", "ARCHIVE"]
fs_dir = []

import os

def visit_fs():
    """Visit file systems to ensure they are mounted."""
    for env in fs_env:
        dir = os.getenv(env)
        if dir != None:
           fs_dir.append(dir)
    [os.path.exists(dir) for dir in fs_dir]

def map_fs(fs):
    """Try to map the filesystem to one of the env variables."""
    for line in open("/etc/mtab"):
        ls = line.split()
        if ls[0] == fs:
            fs = ls[1]
            break
    for env in fs_env:
        edir = os.getenv(env)
        if edir != None:
            if edir == fs:
                return env
    # Failed exact path match, try to match to path components starting from
    # the end (error prone..)
    for env in fs_env:
        edir = os.getenv(env)
        if edir != None:
            eds = edir.split("/")
            eds.reverse()
            for ed in eds:
                if ed in fs:
                    return env
    return fs

def print_quota(quota):
    """Pretty print quotas."""
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
            print '===================================================='
        print 'Quota for ' + ug[0] + ' in units of GB'
        print 'Directory                 Usage      Quota    % used'
        print '----------------------------------------------------'
        for k in fsq.keys():
            use = fsq[k][0].replace('*', ' ')
            use = float(use)/1000**2
            q = float(fsq[k][1])/1000**2
            pcent = use / q * 100
            print "%-20s    %7.2f    %7.2f    %4.1f %%" % (k, use, q, pcent)
    

def run_quota():
    """Run the quota command and parse output.
    
    Checks both user and group quotas. Ignores file limits, just number of
    bytes.
    
    """
    p = os.popen("quota -ug")
    fs = ""
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
                fs = map_fs(ls[0])
            elif splitline:
                curlist[fs] = (ls[0], ls[1])
                splitline = False
            else:
                curlist[map_fs(ls[0])] = (ls[1], ls[2])
    p.close()
    print_quota(myquota)




def quota_main():
    """Main interface of the quota program."""
    visit_fs()
    run_quota()


if __name__=="__main__":
    quota_main()


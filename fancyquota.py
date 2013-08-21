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

The program tries to read a configuration file from the following locations

/etc/fancyquota.cfg
~/.config/fancyquota.cfg
fancyquota.cfg

In the config file, you can put a list of directories, and environment
variables pointing to directories, which must be visited (i.e. make
the automounter mount them if they are unmounted). Multiple entries
can be present, separated by commas. An example config file:

[visit]
envs=HOME, WRKDIR
dirs=/usr,/tmp
"""

import os

def parse_config():
    import ConfigParser
    home_conf = os.path.expanduser('~/.config/fancyquota.cfg')
    config = ConfigParser.SafeConfigParser()
    config.read(['/etc/fancyquota.cfg', home_conf, 'fancyquota.cfg'])
    if not config.has_section('visit'):
        return []
    envstr = config.get('visit', 'envs')
    dirs = []
    for e in envstr.split(','):
        d = os.getenv(e.strip())
        if d:
            dirs.append(d)
    dirstr = config.get('visit', 'dirs')
    for d in dirstr.split(','):
        dirs.append(d.strip())
    return dirs

def visit_fs(dirs):
    """Visit file systems to ensure they are mounted."""
    for dir in dirs:
        try:
            os.stat(dir)
        except OSError:
            pass

def read_mounts():
    """Read /proc/self/mounts, return a {fs:[mountpoint,fstype]} dict"""
    m = {}
    with open('/proc/self/mounts') as f:
        for line in f.readlines():
            ls = line.split()
            m[ls[0]] = [ls[1], ls[2]]
    return m

def map_fs(fs, mp):
    """Map the filesystem to a mount point. 

    In case of autofs where quota confusingly reports the quota for
    another file system, try to find the correct mount point.
    """
    # Try to match to another mountpoint by chopping off a component
    # from the end and replacing it with the username. This should
    # deal with the automounter wildcard mounts hopefully without
    # accidentally matching incorrectly.

    fschop = os.path.dirname(fs)
    fsme = os.path.join(fschop, os.getenv("LOGNAME"))
    if fsme in mp:
        return mp[fsme]
    else:
        return mp[fs]

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
    mp = read_mounts()
    myquota = []
    for line in p.readlines():
        if line.find("Disk quotas for") != -1:
            eind = line.find(' (')
            current = " ".join(line[:eind].split()[3:])
            curlist = {}
            myquota.append((current, curlist))
        elif line.find("     Filesystem  blocks   quota   limit") == -1:
            ls = line.split()
            if len(ls) == 1:
                splitline = True
                fs = map_fs(ls[0], mp)[0]
            elif splitline:
                curlist[fs] = (ls[0], ls[1], ls[2], ls[3])
                splitline = False
            else:
                curlist[map_fs(ls[0], mp)[0]] = (ls[1], ls[2], ls[3], ls[4])
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
    dirs = parse_config()
    visit_fs(dirs)
    run_quota()


if __name__=="__main__":
    quota_main()


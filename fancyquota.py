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
        print hfmt % ('Directory', 'Usage', 'Quota', '%used', 'Limit', 'Grace')
        for k in fsq.keys():
            use = float(fsq[k][0])/1000**2
            q = float(fsq[k][1])/1000**2
            hq = float(fsq[k][2]) / 1000**2
            if (hq > q):
                grace = fsq[k][3]
            else:
                grace = ''
            pcent = use / q * 100
            fmt = "%-" + str(dlen) + "s %7.2f %10.2f %9.0f %9.2f %s"
            print fmt % (k, use, q, pcent, hq, grace)

def parse_quota_line(ls):
    """Parse the quota numbers output, return a tuple (usage, quota, limit, grace).

    First 3 elements are integers, grace is a string.
    """
    if type(ls) == 'str':
        ls = ls.split()
    if len(ls) == 6: # Not over quota, grace field empty
        q = (ls[0], ls[1], ls[2], '')
    elif len(ls) == 7: # Either blocks or files quota exceeded
        grace = ''
        try:
            tmp = int(ls[3])
        except ValueError:
            grace = line[3]
            q = (ls[0], ls[1], ls[2], grace)
    else: # Both files and block quota exceeded
        q = (ls[0], ls[1], ls[2], ls[3])
    # If over block quota, there will be a '*', remove it
    qb = q[0].replace('*', '')
    return (int(qb), int(q[1]), int(q[2]), q[3])

def run_quota(mp):
    """Run the quota command and parse output.
    
    Checks both user and group quotas. Ignores file limits, just number of
    bytes.
    
    """
    p = os.popen("/usr/bin/quota -ug")
    fs = ""
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
                curlist[fs] = parse_quota_line(ls)
                splitline = False
            else:
                curlist[map_fs(ls[0], mp)[0]] = parse_quota_line(ls[1:])
    p.close()
    print_quota(myquota)
    done_mp = set()
    for q in myquota:
        for e in q[1]:
            done_mp.add(e)
    return done_mp

def nfs_proj_quota(mps, done_mp):
    """XFS project quotas over NFS are shown as the size of the file system"""
    showed_head = False
    dlen = 12
    for fs in mps:
        mp = map_fs(fs, mps)[0]
        if mps[fs][1][:3] == 'nfs' and mp not in done_mp:
            td = len(mp) + 4
            if td > dlen:
                dlen = td
    fmt = "%-" + str(dlen) + "s %7.2f %10.2f %9d"
    for fs in mps:
        mp = map_fs(fs, mps)[0]
        if mps[fs][1][:3] == 'nfs' and mp not in done_mp:
            if not showed_head:
                print '-' * (dlen + 29)
                print 'Project quotas'
                hfmt = '%-' + str(dlen) + 's %7s %10s %9s'
                print  hfmt % ('Directory', 'Usage', 'Quota', '% used')
                showed_head = True
            svfs = os.statvfs(mp)
            used = svfs.f_blocks - svfs.f_bfree
            nonroot_tot = used + svfs.f_bavail
            u100 = used * 100
            usedpct = u100 / nonroot_tot + (u100 % nonroot_tot != 0)
            scale = float(svfs.f_frsize) / 1000**3
            #usage = float(svfs.f_blocks - svfs.f_bavail) * svfs.f_frsize / 1000**3
            #fssize = float(svfs.f_blocks) * svfs.f_frsize / 1000**3
            #used = float(usage) / fssize * 100
            print  fmt % (mp, used * scale, nonroot_tot * scale, usedpct)
            
    

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
    fss = read_mounts()
    done_mp = run_quota(fss)
    nfs_proj_quota(fss, done_mp)


if __name__=="__main__":
    quota_main()


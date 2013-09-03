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
can be present, separated by commas. An example config file section:

[visit]
envs=HOME, WRKDIR
dirs=/usr,/tmp

One can also specify settings for a Lustre quota gateway in the
section [lquotagw]. Example:

[lquotagw]
url=http://127.0.0.1/
dirs=/scratch, /work
"""

import os

def parse_config():
    import ConfigParser
    home_conf = os.path.expanduser('~/.config/fancyquota.cfg')
    config = ConfigParser.SafeConfigParser()
    config.read(['/etc/fancyquota.cfg', home_conf, 'fancyquota.cfg'])
    dirs = []
    if config.has_section('visit'):
        envstr = config.get('visit', 'envs')
        for e in envstr.split(','):
            d = os.getenv(e.strip())
            if d:
                dirs.append(d)
        dirstr = config.get('visit', 'dirs')
        for d in dirstr.split(','):
            dirs.append(d.strip())
    lquota = {}
    if config.has_section('lquotagw'):
        lquota['url'] = config.get('lquotagw', 'url')
        dirstr = config.get('lquotagw', 'dirs')
        ld = []
        for d in dirstr.split(','):
            ld.append(d.strip())
        lquota['dirs'] = ld
    else:
        lquota['url'] = 'http://127.0.0.1'
        lquota['dirs'] = []
    return dirs, lquota

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

def size_to_human(val):
    """Convert a value in bytes to human readable format"""
    if val >= 10**15:
        val /= 10.**15
        suff = 'P'
    elif val >= 10**12:
        val /= 10.**12
        suff = 'T'
    elif val >= 10**9:
        val /= 10.**9
        suff = 'G'
    elif val >= 10**6:
        val /= 10.**6
        suff = 'M'
    elif val >= 10**3:
        val /= 10.**3
        suff = 'k'
    else:
        suff = ''
    return '%6.1f%s' % (val, suff)

def print_header():
    """Print output header"""
    hfmt = '%-19s %-20s %7s %5s %7s %7s %9s'
    print hfmt % ('User/Group', 'Directory', 'Usage', 'Used%', 'Quota', 'Limit', 'Grace')

def print_quota(quota):
    """Pretty print quotas.

    Input is a list, where each element is a tuple (ug, qd), where
    'ug' is a string 'user foo' or 'group bar' specifying which
    user/group the quota applies to. 'qd' is a dict where the keys are
    mountpoints, and the values is a tuple (usage, quota, limit,
    grace) of ints.
    """
    from datetime import date
    fmt = "%-19s %-20s %7s %5.0f %7s %7s %s"
    for ug in quota:
        fsq = ug[1]
        quotas = []
        for vals in fsq.values():
            quotas.append(int(vals[1]))
        s = ug[0].split()
        if s[0] == 'user':
            ugstr = 'u:'
        else:
            ugstr = 'g:'
        for e in s[1:]:
            ugstr += e + ' '
        ugstr = ugstr.strip()
        for k in fsq.keys():
            use = size_to_human(fsq[k][0])
            q = size_to_human(fsq[k][1])
            hq = size_to_human(fsq[k][2])
            try:
                gr = int(fsq[k][3])
                if (gr != 0):
                    now = date.today()
                    gdate = date.fromtimestamp(gr)
                    td = gdate - now
                    grace = str(td.days) + 'days'
                else:
                    grace = ''
            except ValueError:
                grace = fsq[k][3]
            try:
                pcent = float(fsq[k][0]) / fsq[k][1] * 100
            except ZeroDivisionError:
                pcent = float('Inf')
            print fmt % (ugstr, k, use, pcent, q, hq, grace)


def run_quota(mp):
    """Run the quota command and parse output.
    
    Checks both user and group quotas. Ignores file limits, just number of
    bytes.
    
    """
    p = os.popen("/usr/bin/quota -ugwp")
    fs = ""
    myquota = []
    bs = 1024 # BLOCK_SIZE from sys/mount.h
    for line in p.readlines():
        if line.find("Disk quotas for") != -1:
            eind = line.find(' (')
            current = " ".join(line[:eind].split()[3:])
            curlist = {}
            myquota.append((current, curlist))
        elif line.find("     Filesystem  blocks   quota   limit") == -1:
            ls = line.split()
            # If over block quota, there will be a '*', remove it
            qb = int(ls[1].replace('*', '')) * bs
            curlist[map_fs(ls[0], mp)[0]] = (qb, int(ls[2]) * bs, \
                                                 int(ls[3]) * bs, int(ls[4]))
    p.close()
    print_quota(myquota)
    done_mp = set()
    for q in myquota:
        for e in q[1]:
            done_mp.add(e)
    return done_mp

def nfs_proj_quota(mps, done_mp):
    """XFS project quotas over NFS are shown as the size of the file system"""
    fmt = "%-19s %-20s %7s %5d %7s %7s"
    for fs in mps:
        mp = map_fs(fs, mps)[0]
        if mps[fs][1][:3] == 'nfs' and mp not in done_mp:
            svfs = os.statvfs(mp)
            used = svfs.f_blocks - svfs.f_bfree
            nonroot_tot = used + svfs.f_bavail
            u100 = used * 100
            usedpct = u100 / nonroot_tot + (u100 % nonroot_tot != 0)
            used = size_to_human(used * svfs.f_frsize)
            nonroot_tot = size_to_human(nonroot_tot * svfs.f_frsize)
            print  fmt % ('', mp, used, usedpct, '', nonroot_tot)

def nfs_lustre_quota(fss, lquota):
    """Hack to show Lustre group quotas over NFS

    When Lustre is re-exported over NFS and normal quota doesn't work
    one can setup a simple script on a gateway machine which queries
    the Lustre quota ('lfs quota').
    """
    import urllib2, grp
    myquota = []
    kb = 1024
    mygids = os.getgroups()
    for fs in fss:
        mp = map_fs(fs, fss)[0]
        for ld in lquota['dirs']:
            # O(n**2), argh
            if fss[fs][1][:3] == 'nfs' and ld in mp:
                gid = os.stat(mp).st_gid
                if gid in mygids:
                    url = lquota['url'] + '/?gid=' + str(gid)
                    lquotares = urllib2.urlopen(url).read()
                    lls = lquotares.split()
                    if lls[4] == '-':
                        grace = 0
                    else:
                        grace = lls[4]
                    group = grp.getgrgid(gid).gr_name
                    myquota.append(("group " + group, \
                                        {mp:(int(lls[1]) * kb, \
                                                 int(lls[2]) * kb, \
                                                 int(lls[3]) * kb, grace)}))

    print_quota(myquota)
    done_mp = set()
    for q in myquota:
        for e in q[1]:
            done_mp.add(e)
    return done_mp

def quota_main():
    """Main interface of the quota program."""
    from optparse import OptionParser
    usage = """%prog [options]

Print out disk quotas in a nice way, try to work with automounted file
systems, XFS project quotas over NFS, and Lustre filesystems
re-exported over NFS.
"""
    parser = OptionParser(usage, version="1.4")
    parser.parse_args()
    dirs, lquota = parse_config()
    visit_fs(dirs)
    fss = read_mounts()
    print_header()
    done_mp = run_quota(fss)
    done_mp2 = nfs_lustre_quota(fss, lquota)
    done_mp = done_mp.union(done_mp2)
    nfs_proj_quota(fss, done_mp)


if __name__=="__main__":
    quota_main()


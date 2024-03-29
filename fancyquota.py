#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# vim: set fileencoding=utf-8

"""
Copyright (c) 2008-2020 Janne Blomqvist

This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""

"""Print out quota information.

This program tries to print out quota in a sensible way that works with the
automounter.  

The program tries to read a configuration file from the following locations

- /etc/fancyquota.cfg
- $XDG_CONFIG_HOME/fancyquota.cfg or ~/.config/fancyquota.cfg if
  XDF_CONFIG_HOME is not set
- fancyquota.cfg

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

It's possible to specify a list of groups for which quota will not be
displayed. This can be useful to filter out e.g. the default primary
group or such. Example:

[filter]
groups = domain users

"""

import os

def parse_config():
    import configparser
    config_home = os.getenv('XDG_CONFIG_HOME')
    if not config_home:
        home_conf = os.path.expanduser('~/.config/fancyquota.cfg')
    else:
        home_conf = os.path.join(config_home, 'fancyquota.cfg')
    config = configparser.ConfigParser()
    config.read(['/etc/fancyquota.cfg', home_conf, 'fancyquota.cfg'])
    dirs = []
    if config.has_section('visit'):
        if config.has_option('visit', 'envs'):
            envstr = config.get('visit', 'envs')
            for e in envstr.split(','):
                d = os.getenv(e.strip())
                if d:
                    dirs.append(d)
        if config.has_option('visit', 'dirs'):
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
    fgroups = []
    if config.has_section('filter'):
        gstr = config.get('filter', 'groups')
        for g in gstr.split(','):
            fgroups.append(g.strip())
    # Make sure every dir ends with a "/", otherwise autofs won't
    # mount it if it's an autofs mountpoint.
    for i, d in enumerate(dirs):
        dirs[i] = os.path.join(d, "")
    return dirs, lquota, fgroups

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

def get_console_width():
    """Get the width of the console.

    Returns 80 <= console width <= 132
    """
    import os
    env = os.environ
    def ioctl_GWINSZ(fd):
        try:
            import fcntl, termios, struct, os
            cr = struct.unpack('HHHH', fcntl.ioctl(fd, termios.TIOCGWINSZ,
                                                   struct.pack('HHHH', 0, 
                                                               0, 0, 0)))
        except:
            return
        return cr[1]
    cr = ioctl_GWINSZ(1) # stdout
    if not cr:
        cr = ioctl_GWINSZ(0) or ioctl_GWINSZ(1) or ioctl_GWINSZ(2)
    if not cr:
        try:
            fd = os.open(os.ctermid(), os.O_RDONLY)
            cr = ioctl_GWINSZ(fd)
            os.close(fd)
        except:
            pass
    if not cr:
        cr = env.get('COLUMNS', 80)

        ### Use get(key[, default]) instead of a try/catch
        #try:
        #    cr = (env['LINES'], env['COLUMNS'])
        #except:
        #    cr = (25, 80)
    return min(max(int(cr), 80), 132)

def print_header():
    """Print output header"""
    dir_width = console_width - 60  # console_width >= 80
    hfmt = '%-19s %-*s %7s %5s %7s %7s %9s'
    print(hfmt % ('User/Group', dir_width, 'Directory', 'Usage', 'Used%',
                  'Quota', 'Limit', 'Grace'))

def print_quota(quota):
    """Pretty print quotas.

    Input is a list, where each element is a tuple (ug, ugname, qd),
    where 'ug' is a string 'user' or 'group' specifying whether it's a
    user or group quota. 'ugname' is the name of the user/group the
    quota applies to. 'qd' is a dict where the keys are mountpoints,
    and the values is a tuple (usage, quota, limit, grace) of ints.
    """
    from datetime import date
    fmt = "%-19s %-*s %7s %5.0f %7s %7s %s"
    dir_width = console_width - 60
    for ug in quota:
        fsq = ug[2]
        quotas = []
        for vals in fsq.values():
            quotas.append(int(vals[1]))
        s = ug[0]
        if s == 'user':
            ugstr = 'u:'
        else:
            ugstr = 'g:'
        ugstr += ug[1]
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
            print(fmt % (ugstr, dir_width, k, use, pcent, q, hq, grace))


def run_quota(mp, fgroups):
    """Run the quota command and parse output.
    
    Checks both user and group quotas. Ignores file limits, just number of
    bytes.
    
    """
    from subprocess import Popen, PIPE
    devnull = open(os.devnull, 'w')
    p = Popen(['/usr/bin/quota', '-ugwp'], stdout=PIPE, stderr=devnull, text=True).stdout
    fs = ""
    myquota = []
    bs = 1024 # BLOCK_SIZE from sys/mount.h
    for line in p.readlines():
        if line.find("Disk quotas for") != -1:
            eind = line.find(' (')
            ls = line[:eind].split()[3:]
            ug = ls[0] # 'user' or 'group'
            usrgrpname = " ".join(ls[1:]) # Name of user/group
            curlist = {}
            myquota.append((ug, usrgrpname, curlist))
        elif line.find("     Filesystem  blocks   quota   limit") == -1:
            ls = line.split()
            # If over block quota, there will be a '*', remove it
            qb = int(ls[1].replace('*', '')) * bs
            curlist[map_fs(ls[0], mp)[0]] = (qb, int(ls[2]) * bs, \
                                                 int(ls[3]) * bs, int(ls[4]))
    p.close()
    devnull.close()
    done_mp = set()
    for q in myquota:
        for e in q[2]:
            done_mp.add(e)
    q_to_del = []
    myuid = os.geteuid()
    for q in myquota:
        if myuid != 0 and q[0] == 'group' and q[1] in fgroups:
            q_to_del.append(q)
    for q in q_to_del:
        myquota.remove(q)
    for q in myquota:
        mp_to_del = []        
        for e in q[2]:
            if not os.access(e, os.R_OK):
                mp_to_del.append(e)
        for e in mp_to_del:
            del q[2][e]
    print_quota(myquota)
    return done_mp

def nfs_proj_quota(mps, done_mp):
    """XFS project quotas over NFS are shown as the size of the file system"""
    fmt = "%-19s %-*s %7s %5d %7s %7s"
    dir_width = console_width - 60
    for fs in mps:
        mp = map_fs(fs, mps)[0]
        if mps[fs][1][:3] == 'nfs' and mp not in done_mp:
            if not os.access(mp, os.R_OK):
                # If the user doesn't have even read access, don't
                # bother showing quota
                continue
            svfs = os.statvfs(mp)
            used = svfs.f_blocks - svfs.f_bfree
            nonroot_tot = used + svfs.f_bavail
            u100 = used * 100
            usedpct = u100 / nonroot_tot + (u100 % nonroot_tot != 0)
            used = size_to_human(used * svfs.f_frsize)
            nonroot_tot = size_to_human(nonroot_tot * svfs.f_frsize)
            print(fmt % ('', dir_width, mp, used, usedpct, '', nonroot_tot))

def nfs_lustre_quota(fss, lquota, fgroups):
    """Hack to show Lustre group quotas over NFS

    When Lustre is re-exported over NFS and normal quota doesn't work
    one can setup a simple script on a gateway machine which queries
    the Lustre quota ('lfs quota').
    """
    import grp
    from urllib.request import urlopen
    myquota = []
    kb = 1024
    mygids = os.getgroups()
    fgids = set()
    for g in fgroups:
        try:
            fgids.add(grp.getgrnam(g).gr_gid)
        except KeyError:
            pass
    done_mp = set()
    for fs in fss:
        mp = map_fs(fs, fss)[0]
        for ld in lquota['dirs']:
            # O(n**2), argh
            if fss[fs][1][:3] == 'nfs' and ld in mp:
                done_mp.add(mp)
                try:
                    gid = os.stat(mp).st_gid
                except OSError:
                    continue
                if gid in mygids and gid not in fgids:
                    url = lquota['url'] + '/?gid=' + str(gid)
                    lquotares = urlopen(url).read()
                    lls = lquotares.split()
                    if lls[4] == '-':
                        grace = 0
                    else:
                        grace = lls[4]
                    group = grp.getgrgid(gid).gr_name
                    # If over block quota, there will be a '*', remove it
                    qb = int(lls[1].replace('*', '')) * kb
                    myquota.append(('group', group, \
                                        {mp:(qb, \
                                                 int(lls[2]) * kb, \
                                                 int(lls[3]) * kb, grace)}))

    print_quota(myquota)
    return done_mp

def quota_main():
    """Main interface of the quota program."""
    from optparse import OptionParser
    usage = """%prog [options]

Print out disk quotas in a nice way, try to work with automounted file
systems, XFS project quotas over NFS, and Lustre filesystems
re-exported over NFS.
"""
    parser = OptionParser(usage, version="1.8")
    parser.parse_args()
    dirs, lquota, fgroups = parse_config()
    visit_fs(dirs)
    fss = read_mounts()
    global console_width
    console_width = get_console_width()
    print_header()
    done_mp = run_quota(fss, fgroups)
    done_mp2 = nfs_lustre_quota(fss, lquota, fgroups)
    done_mp = done_mp.union(done_mp2)
    nfs_proj_quota(fss, done_mp)


if __name__=="__main__":
    quota_main()


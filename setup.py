#!/usr/bin/python3

from __future__ import print_function

import os
import sys
import re
import glob
import subprocess
from os.path import dirname, abspath, join, split
from distutils.core import Extension, Command
from distutils      import version

# Building in pbuilder for Precise with Python 3.2 and 
# python3-distutils-extra 2.34-0ubuntu0.1 
# still needs this workaround, else UnicodeDecodeError.
# Skip this in python 3.3 or 'open' calls will fail later.
if sys.version_info.major == 3 and \
   sys.version_info.minor <= 2:
    import locale
    locale.getpreferredencoding = lambda *x: 'UTF-8'

try:
    import DistUtilsExtra.auto
except ImportError:
    print('To build Onboard you need https://launchpad.net/python-distutils-extra', file=sys.stderr)
    sys.exit(1)

try:
    # try python 3
    from subprocess import getstatusoutput
except:
    # python 2 fallback
    from commands import getstatusoutput

current_ver = version.StrictVersion(DistUtilsExtra.auto.__version__)
required_ver = version.StrictVersion('2.12')
assert current_ver >= required_ver , 'needs DistUtilsExtra.auto >= 2.12'

def pkgconfig(*packages, **kw):
    command = "pkg-config --libs --cflags %s" % ' '.join(packages)
    status, output = getstatusoutput(command)

    # print command and ouput to console to aid in debugging
    if "build" in sys.argv or \
       "build_ext" in sys.argv:
        print("setup.py: running pkg-config:", command)
        print("setup.py:", output)

    if status != 0:
        print('setup.py: pkg-config returned exit code %d' % status, file=sys.stderr)
        print('setup.py: sdist needs libgtk-3-dev, libxtst-dev and libdconf-dev')
        sys.exit(1)


    flag_map = {'-I': 'include_dirs', '-L': 'library_dirs', '-l': 'libraries'}
    for token in output.split():
        if token[:2] in flag_map:
            kw.setdefault(flag_map.get(token[:2]), []).append(token[2:])
        else:
            kw.setdefault('extra_link_args', []).append(token)
    for k, v in kw.items():
        kw[k] = list(set(v))
    return kw


def get_pkg_version(package):
    """ get major, minor version of package """
    command = "pkg-config --modversion " + package
    status, output = getstatusoutput(command)
    if status != 0:
        print("setup.py: get_pkg_version({}): "
              "pkg-config returned exit code {}" \
              .format(repr(package), status), file=sys.stderr)
        sys.exit(2)

    version = re.search('(?:(?:\d+)\.)+\d+', output).group()
    components = version.split(".")
    major, minor = int(components[0]), int(components[1])
    revision = int(components[2]) if len(components) >= 3 else 0
    return major, minor, revision


# Make xgettext extract translatable strings from _format() calls too.
var = "XGETTEXT_ARGS"
os.environ[var] = os.environ.get(var, "") + " --keyword=_format"


##### private extension 'osk' #####

OSK_EXTENSION = 'Onboard.osk'

SOURCES = ['osk_module.c',
           'osk_devices.c',
           'osk_util.c',
           'osk_dconf.c',
           'osk_struts.c',
           'osk_audio.c'
          ]
SOURCES = ['Onboard/osk/' + x for x in SOURCES]

DEPENDS = ['osk_module.h',
           'osk_devices.h',
           'osk_util.h',
           'osk_struts.h',
           'osk_audio.h'
          ]
# even MINOR numbers for stable versions
MACROS = [('MAJOR_VERSION', '0'),
          ('MINOR_VERSION', '2'),
          ('MICRO_VERSION', '0')]

# dconf had an API change between 0.12 and 0.13, tell osk
major, minor, revision = get_pkg_version("dconf")
if major == 0 and minor <= 12:
    MACROS.append(("DCONF_API_0", 1))
print("found dconf version {}.{}.{}".format(major, minor, revision))


module = Extension(
    OSK_EXTENSION,

    define_macros = MACROS,

    sources = SOURCES,
    depends = DEPENDS,   # trigger rebuild on changes to these

    **pkgconfig('gdk-3.0', 'x11', 'xi', 'xtst', 'dconf', 'libcanberra')
)


#### custom test command ####'

class TestCommand(Command):

    user_options = []

    def initialize_options(self):
        pass

    def finalize_options(self):
        pass

    def run(self):
        import nose
        if nose.run(argv=[__file__, "--with-doctest"]):
            sys.exit( 0 )
        else:
            sys.exit( 1 )


##### setup #####

DistUtilsExtra.auto.setup(
    name = 'onboard',
    version = '0.99.0~alpha1~tr1190',
    author = 'Chris Jones',
    author_email = 'chris.e.jones@gmail.com',
    maintainer = 'Ubuntu Core Developers',
    maintainer_email = 'ubuntu-devel-discuss@lists.ubuntu.com',
    url = 'http://launchpad.net/onboard/',
    license = 'gpl',
    description = 'Simple On-screen Keyboard',

    packages = ['Onboard'],

    data_files = [('share/glib-2.0/schemas', glob.glob('data/*.gschema.xml')),
                  ('share/GConf/gsettings', glob.glob('data/*.convert')),
                  ('share/onboard', glob.glob('AUTHORS')),
                  ('share/onboard', glob.glob('CHANGELOG')),
                  ('share/onboard', glob.glob('COPYING')),
                  ('share/onboard', glob.glob('NEWS')),
                  ('share/onboard', glob.glob('README')),
                  ('share/onboard', glob.glob('onboard-defaults.conf.example')),
                  ('share/onboard', glob.glob('onboard-defaults.conf.example.nexus7')),
                  ('share/icons/hicolor/scalable/apps', glob.glob('icons/hicolor/*')),
                  ('share/icons/ubuntu-mono-dark/status/22', glob.glob('icons/ubuntu-mono-dark/*')),
                  ('share/icons/ubuntu-mono-light/status/22', glob.glob('icons/ubuntu-mono-light/*')),
                  ('share/onboard/docs', glob.glob('docs/*')),
                  ('share/onboard/layouts', glob.glob('layouts/*.*')),
                  ('share/onboard/layouts/images', glob.glob('layouts/images/*')),
                  ('share/onboard/themes', glob.glob('themes/*')),
                  ('share/onboard/scripts', glob.glob('scripts/*')),
                  ('/etc/xdg/autostart', glob.glob('data/onboard-autostart.desktop'))],

    scripts = ['onboard', 'onboard-settings'],

    requires = [OSK_EXTENSION],

    ext_modules = [module],

    cmdclass = {'test': TestCommand},
)

# Link the osk extension back to the project directory
# so Onboard can be run from source as usual.
# Remove this at any time if there is a better way.
if "build" in sys.argv or \
   "build_ext" in sys.argv:
    root = dirname(abspath(__file__))
    pattern = join(root, 'build', 'lib*{}.*'.format(sys.version_info.major),
                         'Onboard', 'osk*.so')
    files = glob.glob(pattern)
    for file in files:
        dstfile = join("Onboard", split(file)[1])
        print("symlinking {} to {}".format(file, dstfile))

        try: os.unlink(dstfile)
        except OSError: pass
        os.symlink(file, dstfile)


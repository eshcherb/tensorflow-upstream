# Copyright 2017 The TensorFlow Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================
"""configure script to get build parameters from user."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import errno
import os
import platform
import re
import subprocess
import sys

# pylint: disable=g-import-not-at-top
try:
  from shutil import which
except ImportError:
  from distutils.spawn import find_executable as which
# pylint: enable=g-import-not-at-top

_TF_BAZELRC = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           '.tf_configure.bazelrc')
_TF_WORKSPACE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             'WORKSPACE')
_DEFAULT_CUDA_VERSION = '9.0'
_DEFAULT_CUDNN_VERSION = '7'
_DEFAULT_CUDA_COMPUTE_CAPABILITIES = '3.5,5.2'
_DEFAULT_CUDA_PATH = '/usr/local/cuda'
_DEFAULT_CUDA_PATH_LINUX = '/opt/cuda'
_DEFAULT_CUDA_PATH_WIN = ('C:/Program Files/NVIDIA GPU Computing '
                          'Toolkit/CUDA/v%s' % _DEFAULT_CUDA_VERSION)
_TF_OPENCL_VERSION = '1.2'
_DEFAULT_COMPUTECPP_TOOLKIT_PATH = '/usr/local/computecpp'
_DEFAULT_TRISYCL_INCLUDE_DIR = '/usr/local/triSYCL/include'
_SUPPORTED_ANDROID_NDK_VERSIONS = [10, 11, 12, 13, 14, 15]

_DEFAULT_PROMPT_ASK_ATTEMPTS = 10


class UserInputError(Exception):
  pass


def is_windows():
  return platform.system() == 'Windows'


def is_linux():
  return platform.system() == 'Linux'


def is_macos():
  return platform.system() == 'Darwin'


def is_ppc64le():
  return platform.machine() == 'ppc64le'


def is_cygwin():
  return platform.system().startswith('CYGWIN_NT')


def get_input(question):
  try:
    try:
      answer = raw_input(question)
    except NameError:
      answer = input(question)  # pylint: disable=bad-builtin
  except EOFError:
    answer = ''
  return answer


def symlink_force(target, link_name):
  """Force symlink, equivalent of 'ln -sf'.

  Args:
    target: items to link to.
    link_name: name of the link.
  """
  try:
    os.symlink(target, link_name)
  except OSError as e:
    if e.errno == errno.EEXIST:
      os.remove(link_name)
      os.symlink(target, link_name)
    else:
      raise e


def sed_in_place(filename, old, new):
  """Replace old string with new string in file.

  Args:
    filename: string for filename.
    old: string to replace.
    new: new string to replace to.
  """
  with open(filename, 'r') as f:
    filedata = f.read()
  newdata = filedata.replace(old, new)
  with open(filename, 'w') as f:
    f.write(newdata)


def remove_line_with(filename, token):
  """Remove lines that contain token from file.

  Args:
    filename: string for filename.
    token: string token to check if to remove a line from file or not.
  """
  with open(filename, 'r') as f:
    filedata = f.read()

  with open(filename, 'w') as f:
    for line in filedata.strip().split('\n'):
      if token not in line:
        f.write(line + '\n')


def write_to_bazelrc(line):
  with open(_TF_BAZELRC, 'a') as f:
    f.write(line + '\n')


def write_action_env_to_bazelrc(var_name, var):
  write_to_bazelrc('build --action_env %s="%s"' % (var_name, str(var)))


def run_shell(cmd, allow_non_zero=False):
  if allow_non_zero:
    try:
      output = subprocess.check_output(cmd)
    except subprocess.CalledProcessError as e:
      output = e.output
  else:
    output = subprocess.check_output(cmd)
  return output.decode('UTF-8').strip()


def cygpath(path):
  """Convert path from posix to windows."""
  return os.path.abspath(path).replace('\\', '/')


def get_python_path(environ_cp, python_bin_path):
  """Get the python site package paths."""
  python_paths = []
  if environ_cp.get('PYTHONPATH'):
    python_paths = environ_cp.get('PYTHONPATH').split(':')
  try:
    library_paths = run_shell(
        [python_bin_path, '-c',
         'import site; print("\\n".join(site.getsitepackages()))']).split('\n')
  except subprocess.CalledProcessError:
    library_paths = [run_shell(
        [python_bin_path, '-c',
         'from distutils.sysconfig import get_python_lib;'
         'print(get_python_lib())'])]

  all_paths = set(python_paths + library_paths)

  paths = []
  for path in all_paths:
    if os.path.isdir(path):
      paths.append(path)
  return paths


def get_python_major_version(python_bin_path):
  """Get the python major version."""
  return run_shell([python_bin_path, '-c', 'import sys; print(sys.version[0])'])


def setup_python(environ_cp):
  """Setup python related env variables."""
  # Get PYTHON_BIN_PATH, default is the current running python.
  default_python_bin_path = sys.executable
  ask_python_bin_path = ('Please specify the location of python. [Default is '
                         '%s]: ') % default_python_bin_path
  while True:
    python_bin_path = get_from_env_or_user_or_default(
        environ_cp, 'PYTHON_BIN_PATH', ask_python_bin_path,
        default_python_bin_path)
    # Check if the path is valid
    if os.path.isfile(python_bin_path) and os.access(
        python_bin_path, os.X_OK):
      break
    elif not os.path.exists(python_bin_path):
      print('Invalid python path: %s cannot be found.' % python_bin_path)
    else:
      print('%s is not executable.  Is it the python binary?' % python_bin_path)
    environ_cp['PYTHON_BIN_PATH'] = ''

  # Convert python path to Windows style before checking lib and version
  if is_windows() or is_cygwin():
    python_bin_path = cygpath(python_bin_path)

  # Get PYTHON_LIB_PATH
  python_lib_path = environ_cp.get('PYTHON_LIB_PATH')
  if not python_lib_path:
    python_lib_paths = get_python_path(environ_cp, python_bin_path)
    if environ_cp.get('USE_DEFAULT_PYTHON_LIB_PATH') == '1':
      python_lib_path = python_lib_paths[0]
    else:
      print('Found possible Python library paths:\n  %s' %
            '\n  '.join(python_lib_paths))
      default_python_lib_path = python_lib_paths[0]
      python_lib_path = get_input(
          'Please input the desired Python library path to use.  '
          'Default is [%s]\n' % python_lib_paths[0])
      if not python_lib_path:
        python_lib_path = default_python_lib_path
    environ_cp['PYTHON_LIB_PATH'] = python_lib_path

  python_major_version = get_python_major_version(python_bin_path)

  # Convert python path to Windows style before writing into bazel.rc
  if is_windows() or is_cygwin():
    python_lib_path = cygpath(python_lib_path)

  # Set-up env variables used by python_configure.bzl
  write_action_env_to_bazelrc('PYTHON_BIN_PATH', python_bin_path)
  write_action_env_to_bazelrc('PYTHON_LIB_PATH', python_lib_path)
  write_to_bazelrc('build --force_python=py%s' % python_major_version)
  write_to_bazelrc('build --host_force_python=py%s' % python_major_version)
  write_to_bazelrc('build --python_path=\"%s"' % python_bin_path)
  environ_cp['PYTHON_BIN_PATH'] = python_bin_path

  # Write tools/python_bin_path.sh
  with open('tools/python_bin_path.sh', 'w') as f:
    f.write('export PYTHON_BIN_PATH="%s"' % python_bin_path)


def reset_tf_configure_bazelrc():
  """Reset file that contains customized config settings."""
  open(_TF_BAZELRC, 'w').close()

  home = os.path.expanduser('~')
  if not os.path.exists('.bazelrc'):
    if os.path.exists(os.path.join(home, '.bazelrc')):
      with open('.bazelrc', 'a') as f:
        f.write('import %s/.bazelrc\n' % home.replace('\\', '/'))
    else:
      open('.bazelrc', 'w').close()

  remove_line_with('.bazelrc', 'tf_configure')
  with open('.bazelrc', 'a') as f:
    f.write('import %workspace%/.tf_configure.bazelrc\n')


def cleanup_makefile():
  """Delete any leftover BUILD files from the Makefile build.

  These files could interfere with Bazel parsing.
  """
  makefile_download_dir = 'tensorflow/contrib/makefile/downloads'
  if os.path.isdir(makefile_download_dir):
    for root, _, filenames in os.walk(makefile_download_dir):
      for f in filenames:
        if f.endswith('BUILD'):
          os.remove(os.path.join(root, f))


def get_var(environ_cp,
            var_name,
            query_item,
            enabled_by_default,
            question=None,
            yes_reply=None,
            no_reply=None):
  """Get boolean input from user.

  If var_name is not set in env, ask user to enable query_item or not. If the
  response is empty, use the default.

  Args:
    environ_cp: copy of the os.environ.
    var_name: string for name of environment variable, e.g. "TF_NEED_HDFS".
    query_item: string for feature related to the variable, e.g. "Hadoop File
      System".
    enabled_by_default: boolean for default behavior.
    question: optional string for how to ask for user input.
    yes_reply: optionanl string for reply when feature is enabled.
    no_reply: optional string for reply when feature is disabled.

  Returns:
    boolean value of the variable.

  Raises:
    UserInputError: if an environment variable is set, but it cannot be
      interpreted as a boolean indicator, assume that the user has made a
      scripting error, and will continue to provide invalid input.
      Raise the error to avoid infinitely looping.
  """
  if not question:
    question = 'Do you wish to build TensorFlow with %s support?' % query_item
  if not yes_reply:
    yes_reply = '%s support will be enabled for TensorFlow.' % query_item
  if not no_reply:
    no_reply = 'No %s' % yes_reply

  yes_reply += '\n'
  no_reply += '\n'

  if enabled_by_default:
    question += ' [Y/n]: '
  else:
    question += ' [y/N]: '

  var = environ_cp.get(var_name)
  if var is not None:
    var_content = var.strip().lower()
    if var_content in ('1', 't', 'true', 'y', 'yes'):
      var = True
    elif var_content in ('0', 'f', 'false', 'n', 'no'):
      var = False
    else:
      raise UserInputError('Environment variable %s must be set as a boolean indicator.\n'
                           'The following are accepted as TRUE : %s.\n'
                           'The following are accepted as FALSE: %s.\n'
                           'Current value is %s' %
                           (var_name,
                            ','.join(true_contents),
                            ','.join(false_contents),
                            var))

  while var is None:
    user_input_origin = get_input(question)
    user_input = user_input_origin.strip().lower()
    if user_input == 'y':
      print(yes_reply)
      var = True
    elif user_input == 'n':
      print(no_reply)
      var = False
    elif not user_input:
      if enabled_by_default:
        print(yes_reply)
        var = True
      else:
        print(no_reply)
        var = False
    else:
      print('Invalid selection: %s' % user_input_origin)
  return var


def set_build_var(environ_cp, var_name, query_item, option_name,
                  enabled_by_default, bazel_config_name=None):
  """Set if query_item will be enabled for the build.

  Ask user if query_item will be enabled. Default is used if no input is given.
  Set subprocess environment variable and write to .bazelrc if enabled.

  Args:
    environ_cp: copy of the os.environ.
    var_name: string for name of environment variable, e.g. "TF_NEED_HDFS".
    query_item: string for feature related to the variable, e.g. "Hadoop File
      System".
    option_name: string for option to define in .bazelrc.
    enabled_by_default: boolean for default behavior.
    bazel_config_name: Name for Bazel --config argument to enable build feature.
  """

  var = str(int(get_var(environ_cp, var_name, query_item, enabled_by_default)))
  environ_cp[var_name] = var
  if var == '1':
    write_to_bazelrc('build --define %s=true' % option_name)
  elif bazel_config_name is not None:
    # TODO(mikecase): Migrate all users of configure.py to use --config Bazel
    # options and not to set build configs through environment variables.
    write_to_bazelrc('build:%s --define %s=true'
                     % (bazel_config_name, option_name))


def set_action_env_var(environ_cp,
                       var_name,
                       query_item,
                       enabled_by_default,
                       question=None,
                       yes_reply=None,
                       no_reply=None):
  """Set boolean action_env variable.

  Ask user if query_item will be enabled. Default is used if no input is given.
  Set environment variable and write to .bazelrc.

  Args:
    environ_cp: copy of the os.environ.
    var_name: string for name of environment variable, e.g. "TF_NEED_HDFS".
    query_item: string for feature related to the variable, e.g. "Hadoop File
      System".
    enabled_by_default: boolean for default behavior.
    question: optional string for how to ask for user input.
    yes_reply: optionanl string for reply when feature is enabled.
    no_reply: optional string for reply when feature is disabled.
  """
  var = int(
      get_var(environ_cp, var_name, query_item, enabled_by_default, question,
              yes_reply, no_reply))

  write_action_env_to_bazelrc(var_name, var)
  environ_cp[var_name] = str(var)


def convert_version_to_int(version):
  """Convert a version number to a integer that can be used to compare.

  Version strings of the form X.YZ and X.Y.Z-xxxxx are supported. The
  'xxxxx' part, for instance 'homebrew' on OS/X, is ignored.

  Args:
    version: a version to be converted

  Returns:
    An integer if converted successfully, otherwise return None.
  """
  version = version.split('-')[0]
  version_segments = version.split('.')
  for seg in version_segments:
    if not seg.isdigit():
      return None

  version_str = ''.join(['%03d' % int(seg) for seg in version_segments])
  return int(version_str)


def check_bazel_version(min_version):
  """Check installed bezel version is at least min_version.

  Args:
    min_version: string for minimum bazel version.

  Returns:
    The bazel version detected.
  """
  if which('bazel') is None:
    print('Cannot find bazel. Please install bazel.')
    sys.exit(0)
  curr_version = run_shell(['bazel', '--batch', 'version'])

  for line in curr_version.split('\n'):
    if 'Build label: ' in line:
      curr_version = line.split('Build label: ')[1]
      break

  min_version_int = convert_version_to_int(min_version)
  curr_version_int = convert_version_to_int(curr_version)

  # Check if current bazel version can be detected properly.
  if not curr_version_int:
    print('WARNING: current bazel installation is not a release version.')
    print('Make sure you are running at least bazel %s' % min_version)
    return curr_version

  print('You have bazel %s installed.' % curr_version)

  if curr_version_int < min_version_int:
    print('Please upgrade your bazel installation to version %s or higher to '
          'build TensorFlow!' % min_version)
    sys.exit(0)
  return curr_version


def set_cc_opt_flags(environ_cp):
  """Set up architecture-dependent optimization flags.

  Also append CC optimization flags to bazel.rc..

  Args:
    environ_cp: copy of the os.environ.
  """
  if is_ppc64le():
    # gcc on ppc64le does not support -march, use mcpu instead
    default_cc_opt_flags = '-mcpu=native'
  else:
    default_cc_opt_flags = '-march=native'
  question = ('Please specify optimization flags to use during compilation when'
              ' bazel option "--config=opt" is specified [Default is %s]: '
             ) % default_cc_opt_flags
  cc_opt_flags = get_from_env_or_user_or_default(environ_cp, 'CC_OPT_FLAGS',
                                                 question, default_cc_opt_flags)
  for opt in cc_opt_flags.split():
    write_to_bazelrc('build:opt --copt=%s' % opt)
  # It should be safe on the same build host.
  write_to_bazelrc('build:opt --host_copt=-march=native')
  write_to_bazelrc('build:opt --define with_default_optimizations=true')
  # TODO(mikecase): Remove these default defines once we are able to get
  # TF Lite targets building without them.
  write_to_bazelrc('build --copt=-DGEMMLOWP_ALLOW_SLOW_SCALAR_FALLBACK')
  write_to_bazelrc('build --host_copt=-DGEMMLOWP_ALLOW_SLOW_SCALAR_FALLBACK')


def set_tf_cuda_clang(environ_cp):
  """set TF_CUDA_CLANG action_env.

  Args:
    environ_cp: copy of the os.environ.
  """
  question = 'Do you want to use clang as CUDA compiler?'
  yes_reply = 'Clang will be used as CUDA compiler.'
  no_reply = 'nvcc will be used as CUDA compiler.'
  set_action_env_var(
      environ_cp,
      'TF_CUDA_CLANG',
      None,
      False,
      question=question,
      yes_reply=yes_reply,
      no_reply=no_reply)


def set_tf_download_clang(environ_cp):
  """Set TF_DOWNLOAD_CLANG action_env."""
  question = 'Do you want to download a fresh release of clang? (Experimental)'
  yes_reply = 'Clang will be downloaded and used to compile tensorflow.'
  no_reply = 'Clang will not be downloaded.'
  set_action_env_var(
      environ_cp,
      'TF_DOWNLOAD_CLANG',
      None,
      False,
      question=question,
      yes_reply=yes_reply,
      no_reply=no_reply)


def get_from_env_or_user_or_default(environ_cp, var_name, ask_for_var,
                                    var_default):
  """Get var_name either from env, or user or default.

  If var_name has been set as environment variable, use the preset value, else
  ask for user input. If no input is provided, the default is used.

  Args:
    environ_cp: copy of the os.environ.
    var_name: string for name of environment variable, e.g. "TF_NEED_HDFS".
    ask_for_var: string for how to ask for user input.
    var_default: default value string.

  Returns:
    string value for var_name
  """
  var = environ_cp.get(var_name)
  if not var:
    var = get_input(ask_for_var)
    print('\n')
  if not var:
    var = var_default
  return var


def set_clang_cuda_compiler_path(environ_cp):
  """Set CLANG_CUDA_COMPILER_PATH."""
  default_clang_path = which('clang') or ''
  ask_clang_path = ('Please specify which clang should be used as device and '
                    'host compiler. [Default is %s]: ') % default_clang_path

  while True:
    clang_cuda_compiler_path = get_from_env_or_user_or_default(
        environ_cp, 'CLANG_CUDA_COMPILER_PATH', ask_clang_path,
        default_clang_path)
    if os.path.exists(clang_cuda_compiler_path):
      break

    # Reset and retry
    print('Invalid clang path: %s cannot be found.' % clang_cuda_compiler_path)
    environ_cp['CLANG_CUDA_COMPILER_PATH'] = ''

  # Set CLANG_CUDA_COMPILER_PATH
  environ_cp['CLANG_CUDA_COMPILER_PATH'] = clang_cuda_compiler_path
  write_action_env_to_bazelrc('CLANG_CUDA_COMPILER_PATH',
                              clang_cuda_compiler_path)


def prompt_loop_or_load_from_env(
    environ_cp,
    var_name,
    var_default,
    ask_for_var,
    check_success,
    error_msg,
    suppress_default_error=False,
    n_ask_attempts=_DEFAULT_PROMPT_ASK_ATTEMPTS
):
  """Loop over user prompts for an ENV param until receiving a valid response.

  For the env param var_name, read from the environment or verify user input
  until receiving valid input. When done, set var_name in the environ_cp to its
  new value.

  Args:
    environ_cp: (Dict) copy of the os.environ.
    var_name: (String) string for name of environment variable, e.g. "TF_MYVAR".
    var_default: (String) default value string.
    ask_for_var: (String) string for how to ask for user input.
    check_success: (Function) function that takes one argument and returns a
      boolean. Should return True if the value provided is considered valid. May
      contain a complex error message if error_msg does not provide enough
      information. In that case, set suppress_default_error to True.
    error_msg: (String) String with one and only one '%s'. Formatted with each
      invalid response upon check_success(input) failure.
    suppress_default_error: (Bool) Suppress the above error message in favor of
      one from the check_success function.
    n_ask_attempts: (Integer) Number of times to query for valid input before
      raising an error and quitting.

  Returns:
    [String] The value of var_name after querying for input.

  Raises:
    UserInputError: if a query has been attempted n_ask_attempts times without
      success, assume that the user has made a scripting error, and will continue
      to provide invalid input. Raise the error to avoid infinitely looping.
  """
  default = environ_cp.get(var_name) or var_default
  full_query = '%s [Default is %s]: ' % (
      ask_for_var,
      default,
  )

  for _ in range(n_ask_attempts):
    val = get_from_env_or_user_or_default(environ_cp,
                                          var_name,
                                          full_query,
                                          default)
    if check_success(val):
      break
    if not suppress_default_error:
      print(error_msg % val)
    environ_cp[var_name] = ''
  else:
    raise UserInputError('Invalid %s setting was provided %d times in a row. '
                         'Assuming to be a scripting mistake.' %
                         (var_name, n_ask_attempts))

  environ_cp[var_name] = val
  return val


def create_android_ndk_rule(environ_cp):
  """Set ANDROID_NDK_HOME and write Android NDK WORKSPACE rule."""
  if is_windows() or is_cygwin():
    default_ndk_path = cygpath('%s/Android/Sdk/ndk-bundle' %
                               environ_cp['APPDATA'])
  elif is_macos():
    default_ndk_path = '%s/library/Android/Sdk/ndk-bundle' % environ_cp['HOME']
  else:
    default_ndk_path = '%s/Android/Sdk/ndk-bundle' % environ_cp['HOME']

  def valid_ndk_path(path):
    return (os.path.exists(path) and
            os.path.exists(os.path.join(path, 'source.properties')))

  android_ndk_home_path = prompt_loop_or_load_from_env(
      environ_cp,
      var_name='ANDROID_NDK_HOME',
      var_default=default_ndk_path,
      ask_for_var='Please specify the home path of the Android NDK to use.',
      check_success=valid_ndk_path,
      error_msg=('The path %s or its child file "source.properties" '
                 'does not exist.')
  )

  write_android_ndk_workspace_rule(android_ndk_home_path)


def create_android_sdk_rule(environ_cp):
  """Set Android variables and write Android SDK WORKSPACE rule."""
  if is_windows() or is_cygwin():
    default_sdk_path = cygpath('%s/Android/Sdk' % environ_cp['APPDATA'])
  elif is_macos():
    default_sdk_path = '%s/library/Android/Sdk/ndk-bundle' % environ_cp['HOME']
  else:
    default_sdk_path = '%s/Android/Sdk' % environ_cp['HOME']

  def valid_sdk_path(path):
    return (os.path.exists(path) and
            os.path.exists(os.path.join(path, 'platforms')) and
            os.path.exists(os.path.join(path, 'build-tools')))

  android_sdk_home_path = prompt_loop_or_load_from_env(
      environ_cp,
      var_name='ANDROID_SDK_HOME',
      var_default=default_sdk_path,
      ask_for_var='Please specify the home path of the Android SDK to use.',
      check_success=valid_sdk_path,
      error_msg=('Either %s does not exist, or it does not contain the '
                 'subdirectories "platforms" and "build-tools".'))

  platforms = os.path.join(android_sdk_home_path, 'platforms')
  api_levels = sorted(os.listdir(platforms))
  api_levels = [x.replace('android-', '') for x in api_levels]

  def valid_api_level(api_level):
    return os.path.exists(os.path.join(android_sdk_home_path,
                                       'platforms',
                                       'android-' + api_level))

  android_api_level = prompt_loop_or_load_from_env(
      environ_cp,
      var_name='ANDROID_API_LEVEL',
      var_default=api_levels[-1],
      ask_for_var=('Please specify the Android SDK API level to use. '
                   '[Available levels: %s]') % api_levels,
      check_success=valid_api_level,
      error_msg='Android-%s is not present in the SDK path.')

  build_tools = os.path.join(android_sdk_home_path, 'build-tools')
  versions = sorted(os.listdir(build_tools))

  def valid_build_tools(version):
    return os.path.exists(os.path.join(android_sdk_home_path,
                                       'build-tools',
                                       version))

  android_build_tools_version = prompt_loop_or_load_from_env(
      environ_cp,
      var_name='ANDROID_BUILD_TOOLS_VERSION',
      var_default=versions[-1],
      ask_for_var=('Please specify an Android build tools version to use. '
                   '[Available versions: %s]') % versions,
      check_success=valid_build_tools,
      error_msg=('The selected SDK does not have build-tools version %s '
                 'available.'))

  write_android_sdk_workspace_rule(android_sdk_home_path,
                                   android_build_tools_version,
                                   android_api_level)


def write_android_sdk_workspace_rule(android_sdk_home_path,
                                     android_build_tools_version,
                                     android_api_level):
  print('Writing android_sdk_workspace rule.\n')
  with open(_TF_WORKSPACE, 'a') as f:
    f.write("""
android_sdk_repository(
  name="androidsdk",
  api_level=%s,
  path="%s",
  build_tools_version="%s")\n
""" % (android_api_level, android_sdk_home_path, android_build_tools_version))


def write_android_ndk_workspace_rule(android_ndk_home_path):
  print('Writing android_ndk_workspace rule.')
  ndk_api_level = check_ndk_level(android_ndk_home_path)
  if int(ndk_api_level) not in _SUPPORTED_ANDROID_NDK_VERSIONS:
    print('WARNING: The API level of the NDK in %s is %s, which is not '
          'supported by Bazel (officially supported versions: %s). Please use '
          'another version. Compiling Android targets may result in confusing '
          'errors.\n' % (android_ndk_home_path, ndk_api_level,
                         _SUPPORTED_ANDROID_NDK_VERSIONS))
  with open(_TF_WORKSPACE, 'a') as f:
    f.write("""
android_ndk_repository(
  name="androidndk",
  path="%s",
  api_level=%s)\n
""" % (android_ndk_home_path, ndk_api_level))


def check_ndk_level(android_ndk_home_path):
  """Check the revision number of an Android NDK path."""
  properties_path = '%s/source.properties' % android_ndk_home_path
  if is_windows() or is_cygwin():
    properties_path = cygpath(properties_path)
  with open(properties_path, 'r') as f:
    filedata = f.read()

  revision = re.search(r'Pkg.Revision = (\d+)', filedata)
  if revision:
    return revision.group(1)
  return None


def workspace_has_any_android_rule():
  """Check the WORKSPACE for existing android_*_repository rules."""
  with open(_TF_WORKSPACE, 'r') as f:
    workspace = f.read()
  has_any_rule = re.search(r'^android_[ns]dk_repository',
                           workspace,
                           re.MULTILINE)
  return has_any_rule


def set_gcc_host_compiler_path(environ_cp):
  """Set GCC_HOST_COMPILER_PATH."""
  default_gcc_host_compiler_path = which('gcc') or ''
  cuda_bin_symlink = '%s/bin/gcc' % environ_cp.get('CUDA_TOOLKIT_PATH')

  if os.path.islink(cuda_bin_symlink):
    # os.readlink is only available in linux
    default_gcc_host_compiler_path = os.path.realpath(cuda_bin_symlink)

  gcc_host_compiler_path = prompt_loop_or_load_from_env(
      environ_cp,
      var_name='GCC_HOST_COMPILER_PATH',
      var_default=default_gcc_host_compiler_path,
      ask_for_var=
      'Please specify which gcc should be used by nvcc as the host compiler.',
      check_success=os.path.exists,
      error_msg='Invalid gcc path. %s cannot be found.',
  )

  write_action_env_to_bazelrc('GCC_HOST_COMPILER_PATH', gcc_host_compiler_path)


def set_tf_cuda_version(environ_cp):
  """Set CUDA_TOOLKIT_PATH and TF_CUDA_VERSION."""
  ask_cuda_version = (
      'Please specify the CUDA SDK version you want to use, '
      'e.g. 7.0. [Leave empty to default to CUDA %s]: ') % _DEFAULT_CUDA_VERSION

  for _ in range(_DEFAULT_PROMPT_ASK_ATTEMPTS):
    # Configure the Cuda SDK version to use.
    tf_cuda_version = get_from_env_or_user_or_default(
        environ_cp, 'TF_CUDA_VERSION', ask_cuda_version, _DEFAULT_CUDA_VERSION)

    # Find out where the CUDA toolkit is installed
    default_cuda_path = _DEFAULT_CUDA_PATH
    if is_windows() or is_cygwin():
      default_cuda_path = cygpath(
          environ_cp.get('CUDA_PATH', _DEFAULT_CUDA_PATH_WIN))
    elif is_linux():
      # If the default doesn't exist, try an alternative default.
      if (not os.path.exists(default_cuda_path)
         ) and os.path.exists(_DEFAULT_CUDA_PATH_LINUX):
        default_cuda_path = _DEFAULT_CUDA_PATH_LINUX
    ask_cuda_path = ('Please specify the location where CUDA %s toolkit is'
                     ' installed. Refer to README.md for more details. '
                     '[Default is %s]: ') % (tf_cuda_version, default_cuda_path)
    cuda_toolkit_path = get_from_env_or_user_or_default(
        environ_cp, 'CUDA_TOOLKIT_PATH', ask_cuda_path, default_cuda_path)

    if is_windows():
      cuda_rt_lib_path = 'lib/x64/cudart.lib'
    elif is_linux():
      cuda_rt_lib_path = 'lib64/libcudart.so.%s' % tf_cuda_version
    elif is_macos():
      cuda_rt_lib_path = 'lib/libcudart.%s.dylib' % tf_cuda_version

    cuda_toolkit_path_full = os.path.join(cuda_toolkit_path, cuda_rt_lib_path)
    if os.path.exists(cuda_toolkit_path_full):
      break

    # Reset and retry
    print('Invalid path to CUDA %s toolkit. %s cannot be found' %
          (tf_cuda_version, cuda_toolkit_path_full))
    environ_cp['TF_CUDA_VERSION'] = ''
    environ_cp['CUDA_TOOLKIT_PATH'] = ''

  else:
    raise UserInputError('Invalid TF_CUDA_SETTING setting was provided %d '
                         'times in a row. Assuming to be a scripting mistake.' %
                         _DEFAULT_PROMPT_ASK_ATTEMPTS)

  # Set CUDA_TOOLKIT_PATH and TF_CUDA_VERSION
  environ_cp['CUDA_TOOLKIT_PATH'] = cuda_toolkit_path
  write_action_env_to_bazelrc('CUDA_TOOLKIT_PATH', cuda_toolkit_path)
  environ_cp['TF_CUDA_VERSION'] = tf_cuda_version
  write_action_env_to_bazelrc('TF_CUDA_VERSION', tf_cuda_version)


def set_tf_cudnn_version(environ_cp):
  """Set CUDNN_INSTALL_PATH and TF_CUDNN_VERSION."""
  ask_cudnn_version = (
      'Please specify the cuDNN version you want to use. '
      '[Leave empty to default to cuDNN %s.0]: ') % _DEFAULT_CUDNN_VERSION

  for _ in range(_DEFAULT_PROMPT_ASK_ATTEMPTS):
    tf_cudnn_version = get_from_env_or_user_or_default(
        environ_cp, 'TF_CUDNN_VERSION', ask_cudnn_version,
        _DEFAULT_CUDNN_VERSION)

    default_cudnn_path = environ_cp.get('CUDA_TOOLKIT_PATH')
    ask_cudnn_path = (r'Please specify the location where cuDNN %s library is '
                      'installed. Refer to README.md for more details. [Default'
                      ' is %s]:') % (tf_cudnn_version, default_cudnn_path)
    cudnn_install_path = get_from_env_or_user_or_default(
        environ_cp, 'CUDNN_INSTALL_PATH', ask_cudnn_path, default_cudnn_path)

    # Result returned from "read" will be used unexpanded. That make "~"
    # unusable. Going through one more level of expansion to handle that.
    cudnn_install_path = os.path.realpath(
        os.path.expanduser(cudnn_install_path))
    if is_windows() or is_cygwin():
      cudnn_install_path = cygpath(cudnn_install_path)

    if is_windows():
      cuda_dnn_lib_path = 'lib/x64/cudnn.lib'
      cuda_dnn_lib_alt_path = 'lib/x64/cudnn.lib'
    elif is_linux():
      cuda_dnn_lib_path = 'lib64/libcudnn.so.%s' % tf_cudnn_version
      cuda_dnn_lib_alt_path = 'libcudnn.so.%s' % tf_cudnn_version
    elif is_macos():
      cuda_dnn_lib_path = 'lib/libcudnn.%s.dylib' % tf_cudnn_version
      cuda_dnn_lib_alt_path = 'libcudnn.%s.dylib' % tf_cudnn_version

    cuda_dnn_lib_path_full = os.path.join(cudnn_install_path, cuda_dnn_lib_path)
    cuda_dnn_lib_alt_path_full = os.path.join(cudnn_install_path,
                                              cuda_dnn_lib_alt_path)
    if os.path.exists(cuda_dnn_lib_path_full) or os.path.exists(
        cuda_dnn_lib_alt_path_full):
      break

    # Try another alternative for Linux
    if is_linux():
      ldconfig_bin = which('ldconfig') or '/sbin/ldconfig'
      cudnn_path_from_ldconfig = run_shell([ldconfig_bin, '-p'])
      cudnn_path_from_ldconfig = re.search('.*libcudnn.so .* => (.*)',
                                           cudnn_path_from_ldconfig)
      if cudnn_path_from_ldconfig:
        cudnn_path_from_ldconfig = cudnn_path_from_ldconfig.group(1)
        if os.path.exists('%s.%s' % (cudnn_path_from_ldconfig,
                                     tf_cudnn_version)):
          cudnn_install_path = os.path.dirname(cudnn_path_from_ldconfig)
          break

    # Reset and Retry
    print(
        'Invalid path to cuDNN %s toolkit. None of the following files can be '
        'found:' % tf_cudnn_version)
    print(cuda_dnn_lib_path_full)
    print(cuda_dnn_lib_alt_path_full)
    if is_linux():
      print('%s.%s' % (cudnn_path_from_ldconfig, tf_cudnn_version))

    environ_cp['TF_CUDNN_VERSION'] = ''
  else:
    raise UserInputError('Invalid TF_CUDNN setting was provided %d '
                         'times in a row. Assuming to be a scripting mistake.' %
                         _DEFAULT_PROMPT_ASK_ATTEMPTS)

  # Set CUDNN_INSTALL_PATH and TF_CUDNN_VERSION
  environ_cp['CUDNN_INSTALL_PATH'] = cudnn_install_path
  write_action_env_to_bazelrc('CUDNN_INSTALL_PATH', cudnn_install_path)
  environ_cp['TF_CUDNN_VERSION'] = tf_cudnn_version
  write_action_env_to_bazelrc('TF_CUDNN_VERSION', tf_cudnn_version)


def get_native_cuda_compute_capabilities(environ_cp):
  """Get native cuda compute capabilities.

  Args:
    environ_cp: copy of the os.environ.
  Returns:
    string of native cuda compute capabilities, separated by comma.
  """
  device_query_bin = os.path.join(
      environ_cp.get('CUDA_TOOLKIT_PATH'), 'extras/demo_suite/deviceQuery')
  if os.path.isfile(device_query_bin) and os.access(device_query_bin, os.X_OK):
    try:
      output = run_shell(device_query_bin).split('\n')
      pattern = re.compile('[0-9]*\\.[0-9]*')
      output = [pattern.search(x) for x in output if 'Capability' in x]
      output = ','.join(x.group() for x in output if x is not None)
    except subprocess.CalledProcessError:
      output = ''
  else:
    output = ''
  return output


def set_tf_cuda_compute_capabilities(environ_cp):
  """Set TF_CUDA_COMPUTE_CAPABILITIES."""
  while True:
    native_cuda_compute_capabilities = get_native_cuda_compute_capabilities(
        environ_cp)
    if not native_cuda_compute_capabilities:
      default_cuda_compute_capabilities = _DEFAULT_CUDA_COMPUTE_CAPABILITIES
    else:
      default_cuda_compute_capabilities = native_cuda_compute_capabilities

    ask_cuda_compute_capabilities = (
        'Please specify a list of comma-separated '
        'Cuda compute capabilities you want to '
        'build with.\nYou can find the compute '
        'capability of your device at: '
        'https://developer.nvidia.com/cuda-gpus.\nPlease'
        ' note that each additional compute '
        'capability significantly increases your '
        'build time and binary size. [Default is: %s]' %
        default_cuda_compute_capabilities)
    tf_cuda_compute_capabilities = get_from_env_or_user_or_default(
        environ_cp, 'TF_CUDA_COMPUTE_CAPABILITIES',
        ask_cuda_compute_capabilities, default_cuda_compute_capabilities)
    # Check whether all capabilities from the input is valid
    all_valid = True
    for compute_capability in tf_cuda_compute_capabilities.split(','):
      m = re.match('[0-9]+.[0-9]+', compute_capability)
      if not m:
        print('Invalid compute capability: ' % compute_capability)
        all_valid = False
      else:
        ver = int(m.group(0).split('.')[0])
        if ver < 3:
          print('Only compute capabilities 3.0 or higher are supported.')
          all_valid = False

    if all_valid:
      break

    # Reset and Retry
    environ_cp['TF_CUDA_COMPUTE_CAPABILITIES'] = ''

  # Set TF_CUDA_COMPUTE_CAPABILITIES
  environ_cp['TF_CUDA_COMPUTE_CAPABILITIES'] = tf_cuda_compute_capabilities
  write_action_env_to_bazelrc('TF_CUDA_COMPUTE_CAPABILITIES',
                              tf_cuda_compute_capabilities)


def set_other_cuda_vars(environ_cp):
  """Set other CUDA related variables."""
  if is_windows():
    # The following three variables are needed for MSVC toolchain configuration
    # in Bazel
    environ_cp['CUDA_PATH'] = environ_cp.get('CUDA_TOOLKIT_PATH')
    environ_cp['CUDA_COMPUTE_CAPABILITIES'] = environ_cp.get(
        'TF_CUDA_COMPUTE_CAPABILITIES')
    environ_cp['NO_WHOLE_ARCHIVE_OPTION'] = 1
    write_action_env_to_bazelrc('CUDA_PATH', environ_cp.get('CUDA_PATH'))
    write_action_env_to_bazelrc('CUDA_COMPUTE_CAPABILITIE',
                                environ_cp.get('CUDA_COMPUTE_CAPABILITIE'))
    write_action_env_to_bazelrc('NO_WHOLE_ARCHIVE_OPTION',
                                environ_cp.get('NO_WHOLE_ARCHIVE_OPTION'))
    write_to_bazelrc('build --config=win-cuda')
    write_to_bazelrc('test --config=win-cuda')
  else:
    # If CUDA is enabled, always use GPU during build and test.
    if environ_cp.get('TF_CUDA_CLANG') == '1':
      write_to_bazelrc('build --config=cuda_clang')
      write_to_bazelrc('test --config=cuda_clang')
    else:
      write_to_bazelrc('build --config=cuda')
      write_to_bazelrc('test --config=cuda')


def set_host_cxx_compiler(environ_cp):
  """Set HOST_CXX_COMPILER."""
  default_cxx_host_compiler = which('g++') or ''

  host_cxx_compiler = prompt_loop_or_load_from_env(
      environ_cp,
      var_name='HOST_CXX_COMPILER',
      var_default=default_cxx_host_compiler,
      ask_for_var=('Please specify which C++ compiler should be used as the '
                   'host C++ compiler.'),
      check_success=os.path.exists,
      error_msg='Invalid C++ compiler path. %s cannot be found.',
  )

  write_action_env_to_bazelrc('HOST_CXX_COMPILER', host_cxx_compiler)


def set_host_c_compiler(environ_cp):
  """Set HOST_C_COMPILER."""
  default_c_host_compiler = which('gcc') or ''

  host_c_compiler = prompt_loop_or_load_from_env(
      environ_cp,
      var_name='HOST_C_COMPILER',
      var_default=default_c_host_compiler,
      ask_for_var=('Please specify which C compiler should be used as the host'
                   'C compiler.'),
      check_success=os.path.exists,
      error_msg='Invalid C compiler path. %s cannot be found.',
  )

  write_action_env_to_bazelrc('HOST_C_COMPILER', host_c_compiler)


def set_computecpp_toolkit_path(environ_cp):
  """Set COMPUTECPP_TOOLKIT_PATH."""

  def toolkit_exists(toolkit_path):
    """Check if a computecpp toolkit path is valid."""
    if is_linux():
      sycl_rt_lib_path = 'lib/libComputeCpp.so'
    else:
      sycl_rt_lib_path = ''

    sycl_rt_lib_path_full = os.path.join(toolkit_path,
                                         sycl_rt_lib_path)
    exists = os.path.exists(sycl_rt_lib_path_full)
    if not exists:
      print('Invalid SYCL %s library path. %s cannot be found' %
            (_TF_OPENCL_VERSION, sycl_rt_lib_path_full))
    return exists

  computecpp_toolkit_path = prompt_loop_or_load_from_env(
      environ_cp,
      var_name='COMPUTECPP_TOOLKIT_PATH',
      var_default=_DEFAULT_COMPUTECPP_TOOLKIT_PATH,
      ask_for_var=(
          'Please specify the location where ComputeCpp for SYCL %s is '
          'installed.' % _TF_OPENCL_VERSION),
      check_success=toolkit_exists,
      error_msg='Invalid SYCL compiler path. %s cannot be found.',
      suppress_default_error=True)

  write_action_env_to_bazelrc('COMPUTECPP_TOOLKIT_PATH',
                              computecpp_toolkit_path)

def set_trisycl_include_dir(environ_cp):
  """Set TRISYCL_INCLUDE_DIR"""
  ask_trisycl_include_dir = ('Please specify the location of the triSYCL '
                             'include directory. (Use --config=sycl_trisycl '
                             'when building with Bazel) '
                             '[Default is %s]: '
                             ) % (_DEFAULT_TRISYCL_INCLUDE_DIR)
  while True:
    trisycl_include_dir = get_from_env_or_user_or_default(
      environ_cp, 'TRISYCL_INCLUDE_DIR', ask_trisycl_include_dir,
      _DEFAULT_TRISYCL_INCLUDE_DIR)
    if os.path.exists(trisycl_include_dir):
      break

    print('Invalid triSYCL include directory, %s cannot be found'
          % (trisycl_include_dir))

  # Set TRISYCL_INCLUDE_DIR
  environ_cp['TRISYCL_INCLUDE_DIR'] = trisycl_include_dir
  write_action_env_to_bazelrc('TRISYCL_INCLUDE_DIR',
                              trisycl_include_dir)


def set_mpi_home(environ_cp):
  """Set MPI_HOME."""

  default_mpi_home = which('mpirun') or which('mpiexec') or ''
  default_mpi_home = os.path.dirname(os.path.dirname(default_mpi_home))

  def valid_mpi_path(mpi_home):
    exists = (os.path.exists(os.path.join(mpi_home, 'include')) and
              os.path.exists(os.path.join(mpi_home, 'lib')))
    if not exists:
      print('Invalid path to the MPI Toolkit. %s or %s cannot be found' %
            (os.path.join(mpi_home, 'include'),
             os.path.exists(os.path.join(mpi_home, 'lib'))))
    return exists

  _ = prompt_loop_or_load_from_env(
      environ_cp,
      var_name='MPI_HOME',
      var_default=default_mpi_home,
      ask_for_var='Please specify the MPI toolkit folder.',
      check_success=valid_mpi_path,
      error_msg='',
      suppress_default_error=True)


def set_other_mpi_vars(environ_cp):
  """Set other MPI related variables."""
  # Link the MPI header files
  mpi_home = environ_cp.get('MPI_HOME')
  symlink_force('%s/include/mpi.h' % mpi_home, 'third_party/mpi/mpi.h')

  # Determine if we use OpenMPI or MVAPICH, these require different header files
  # to be included here to make bazel dependency checker happy
  if os.path.exists(os.path.join(mpi_home, 'include/mpi_portable_platform.h')):
    symlink_force(
        os.path.join(mpi_home, 'include/mpi_portable_platform.h'),
        'third_party/mpi/mpi_portable_platform.h')
    # TODO(gunan): avoid editing files in configure
    sed_in_place('third_party/mpi/mpi.bzl', 'MPI_LIB_IS_OPENMPI=False',
                 'MPI_LIB_IS_OPENMPI=True')
  else:
    # MVAPICH / MPICH
    symlink_force(
        os.path.join(mpi_home, 'include/mpio.h'), 'third_party/mpi/mpio.h')
    symlink_force(
        os.path.join(mpi_home, 'include/mpicxx.h'), 'third_party/mpi/mpicxx.h')
    # TODO(gunan): avoid editing files in configure
    sed_in_place('third_party/mpi/mpi.bzl', 'MPI_LIB_IS_OPENMPI=True',
                 'MPI_LIB_IS_OPENMPI=False')

  if os.path.exists(os.path.join(mpi_home, 'lib/libmpi.so')):
    symlink_force(
        os.path.join(mpi_home, 'lib/libmpi.so'), 'third_party/mpi/libmpi.so')
  else:
    raise ValueError('Cannot find the MPI library file in %s/lib' % mpi_home)


def set_mkl():
  write_to_bazelrc('build:mkl --define using_mkl=true')
  write_to_bazelrc('build:mkl -c opt')
  print(
      'Add "--config=mkl" to your bazel command to build with MKL '
      'support.\nPlease note that MKL on MacOS or windows is still not '
      'supported.\nIf you would like to use a local MKL instead of '
      'downloading, please set the environment variable \"TF_MKL_ROOT\" every '
      'time before build.\n')


def set_monolithic():
  # Add --config=monolithic to your bazel command to use a mostly-static
  # build and disable modular op registration support (this will revert to
  # loading TensorFlow with RTLD_GLOBAL in Python). By default (without
  # --config=monolithic), TensorFlow will build with a dependence on
  # //tensorflow:libtensorflow_framework.so.
  write_to_bazelrc('build:monolithic --define framework_shared_object=false')
  # For projects which use TensorFlow as part of a Bazel build process, putting
  # nothing in a bazelrc will default to a monolithic build. The following line
  # opts in to modular op registration support by default:
  write_to_bazelrc('build --define framework_shared_object=true')


def create_android_bazelrc_configs():
  # Flags for --config=android
  write_to_bazelrc('build:android --crosstool_top=//external:android/crosstool')
  write_to_bazelrc(
      'build:android --host_crosstool_top=@bazel_tools//tools/cpp:toolchain')
  # Flags for --config=android_arm
  write_to_bazelrc('build:android_arm --config=android')
  write_to_bazelrc('build:android_arm --cpu=armeabi-v7a')
  # Flags for --config=android_arm64
  write_to_bazelrc('build:android_arm64 --config=android')
  write_to_bazelrc('build:android_arm64 --cpu=arm64-v8a')


def set_grpc_build_flags():
  write_to_bazelrc('build --define grpc_no_ares=true')

def set_windows_build_flags():
  if is_windows():
    # The non-monolithic build is not supported yet
    write_to_bazelrc('build --config monolithic')
    # Suppress warning messages
    write_to_bazelrc('build --copt=-w --host_copt=-w')
    # Output more verbose information when something goes wrong
    write_to_bazelrc('build --verbose_failures')


def main():
  # Make a copy of os.environ to be clear when functions and getting and setting
  # environment variables.
  environ_cp = dict(os.environ)

  check_bazel_version('0.5.4')

  reset_tf_configure_bazelrc()
  cleanup_makefile()
  setup_python(environ_cp)

  if is_windows():
    environ_cp['TF_NEED_S3'] = '0'
    environ_cp['TF_NEED_GCP'] = '0'
    environ_cp['TF_NEED_HDFS'] = '0'
    environ_cp['TF_NEED_JEMALLOC'] = '0'
    environ_cp['TF_NEED_OPENCL_SYCL'] = '0'
    environ_cp['TF_NEED_COMPUTECPP'] = '0'
    environ_cp['TF_NEED_OPENCL'] = '0'
    environ_cp['TF_CUDA_CLANG'] = '0'

  if is_macos():
    environ_cp['TF_NEED_JEMALLOC'] = '0'

  set_build_var(environ_cp, 'TF_NEED_JEMALLOC', 'jemalloc as malloc',
                'with_jemalloc', True)
  set_build_var(environ_cp, 'TF_NEED_GCP', 'Google Cloud Platform',
                'with_gcp_support', True, 'gcp')
  set_build_var(environ_cp, 'TF_NEED_HDFS', 'Hadoop File System',
                'with_hdfs_support', True, 'hdfs')
  set_build_var(environ_cp, 'TF_NEED_S3', 'Amazon S3 File System',
                'with_s3_support', True, 's3')
  set_build_var(environ_cp, 'TF_ENABLE_XLA', 'XLA JIT', 'with_xla_support',
                False, 'xla')
  set_build_var(environ_cp, 'TF_NEED_GDR', 'GDR', 'with_gdr_support',
                False, 'gdr')
  set_build_var(environ_cp, 'TF_NEED_VERBS', 'VERBS', 'with_verbs_support',
                False, 'verbs')

  set_action_env_var(environ_cp, 'TF_NEED_OPENCL_SYCL', 'OpenCL SYCL', False)
  if environ_cp.get('TF_NEED_OPENCL_SYCL') == '1':
    set_host_cxx_compiler(environ_cp)
    set_host_c_compiler(environ_cp)
    set_action_env_var(environ_cp, 'TF_NEED_COMPUTECPP', 'ComputeCPP', True)
    if environ_cp.get('TF_NEED_COMPUTECPP') == '1':
      set_computecpp_toolkit_path(environ_cp)
    else:
      set_trisycl_include_dir(environ_cp)

  set_action_env_var(environ_cp, 'TF_NEED_CUDA', 'CUDA', False)
  if (environ_cp.get('TF_NEED_CUDA') == '1' and
      'TF_CUDA_CONFIG_REPO' not in environ_cp):
    set_tf_cuda_version(environ_cp)
    set_tf_cudnn_version(environ_cp)
    set_tf_cuda_compute_capabilities(environ_cp)

    set_tf_cuda_clang(environ_cp)
    if environ_cp.get('TF_CUDA_CLANG') == '1':
      if not is_windows():
        # Ask if we want to download clang release while building.
        set_tf_download_clang(environ_cp)
      else:
        # We use bazel's generated crosstool on Windows and there is no
        # way to provide downloaded toolchain for that yet.
        # TODO(ibiryukov): Investigate using clang as a cuda compiler on
        # Windows.
        environ_cp['TF_DOWNLOAD_CLANG'] = '0'

      if environ_cp.get('TF_DOWNLOAD_CLANG') != '1':
        # Set up which clang we should use as the cuda / host compiler.
        set_clang_cuda_compiler_path(environ_cp)
    else:
      # Set up which gcc nvcc should use as the host compiler
      # No need to set this on Windows
      if not is_windows():
        set_gcc_host_compiler_path(environ_cp)
    set_other_cuda_vars(environ_cp)

  set_build_var(environ_cp, 'TF_NEED_MPI', 'MPI', 'with_mpi_support', False)
  if environ_cp.get('TF_NEED_MPI') == '1':
    set_mpi_home(environ_cp)
    set_other_mpi_vars(environ_cp)

  set_grpc_build_flags()
  set_cc_opt_flags(environ_cp)
  set_mkl()
  set_monolithic()
  set_windows_build_flags()
  create_android_bazelrc_configs()

  if workspace_has_any_android_rule():
    print('The WORKSPACE file has at least one of ["android_sdk_repository", '
          '"android_ndk_repository"] already set. Will not ask to help '
          'configure the WORKSPACE. Please delete the existing rules to '
          'activate the helper.\n')
  else:
    if get_var(
        environ_cp, 'TF_SET_ANDROID_WORKSPACE', 'android workspace',
        False,
        ('Would you like to interactively configure ./WORKSPACE for '
         'Android builds?'),
        'Searching for NDK and SDK installations.',
        'Not configuring the WORKSPACE for Android builds.'):
      create_android_ndk_rule(environ_cp)
      create_android_sdk_rule(environ_cp)


if __name__ == '__main__':
  main()
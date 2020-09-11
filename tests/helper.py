
import os
import sys
import shutil
import glob
import shlex
import ast
import subprocess as sp
import f90nml

run_cmd = 'mpirun --mca orte_base_help_aggregate 0 --mca opal_abort_print_stack 1 -np 1 {atm_exe} : -np 1 {ice_exe} : -np 1 {ocean_exe}'

def silentremove(filename):
    try:
        os.remove(filename)
    except FileNotFoundError:
        pass

class Helper:

    def __init__(self):
        self.test_dir = os.path.dirname(os.path.realpath(__file__))
        self.test_data_dir = os.path.join(self.test_dir, 'test_data')
        self.atm_exe = os.path.join(self.test_dir, '..',
                                    'build', 'bin', 'yatm.exe')
        self.ice_exe = os.path.join(self.test_dir, '..',
                                    'build', 'bin', 'ice_stub.exe')
        self.ocean_exe = os.path.join(self.test_dir, '..',
                                      'build', 'bin', 'ocean_stub.exe')

    def checksums(self, exp_dir):
        """
        Return checksums for experiment in exp_dir.
        """

        checksums_file = os.path.join(self.test_dir, exp_dir, 'checksums.txt')
        with open(checksums_file) as f:
            checksums = self.filter_checksums(f.read())

        return checksums


    def filter_checksums(self, output):
        """
        Filter out and return checksums from output.
        """

        checksums = filter(lambda x : 'checksum' in x, output.splitlines())

        checksums_dict = {}
        for chk in checksums:
            checksums_dict.update(ast.literal_eval(chk.strip()))

        return checksums_dict


    def filter_dates(self, output):
        """
        Filter out and return checksums from dates.
        """
        pass

    def run_exp(self, exp_dir, restart=False, years_duration=0, months_duration=0, seconds_duration=0):
        """
        Run the test experiment in exp_dir
        """

        def clean_logs():
            for f in glob.glob('log/*.log'):
                silentremove(f)

        def clean_restarts():
            for f in glob.glob('*.nc'):
                silentremove(f)

        def copy_oasis_restarts():
            shutil.copy(os.path.join(self.test_data_dir, 'i2o.nc'), './')
            shutil.copy(os.path.join(self.test_data_dir, 'o2i.nc'), './')

        my_dir = os.path.join(self.test_dir, exp_dir)

        # Update runtime
        if years_duration > 0 or months_duration > 0 or seconds_duration > 0:
            assert not (years_duration > 0 and months_duration > 0)
            assert not (years_duration > 0 and seconds_duration > 0)
            assert not (months_duration > 0 and seconds_duration > 0)
            accessom2_config = os.path.join(my_dir, 'accessom2.nml')
            with open(accessom2_config) as f:
                nml = f90nml.read(f)
                nml['date_manager_nml']['restart_period'] = \
                    [years_duration, months_duration, seconds_duration]
                nml.write(accessom2_config, force=True)

        cur_dir = os.getcwd()
        os.chdir(my_dir)
        try:
            os.makedirs(os.path.join(my_dir, 'log'))
        except FileExistsError:
            pass

        if not restart:
            silentremove('accessom2_restart.nml')

        clean_restarts()
        copy_oasis_restarts()
        clean_logs()

        cmd = shlex.split(run_cmd.format(atm_exe=self.atm_exe,
                                         ice_exe=self.ice_exe,
                                         ocean_exe=self.ocean_exe))
        retcode = 0
        try:
            output = sp.check_output(cmd)
        except sp.CalledProcessError as e:
            retcode = e.returncode

        if retcode != 0:
            return retcode, None, None, None

        log = ''
        with open(os.path.join(my_dir, 'log', 'matmxx.pe00000.log')) as f:
            log += f.read()
            matm_log = log
        with open(os.path.join(my_dir, 'log', 'cicexx.pe00001.log')) as f:
            log += f.read()
        with open(os.path.join(my_dir, 'log', 'mom5xx.pe00002.log')) as f:
            log += f.read()

        with open(os.path.join(my_dir, 'log', 'all.log'), 'w') as f:
            f.write(log)

        # Restore state
        os.chdir(cur_dir)

        return retcode, output.decode('utf-8'), log, matm_log

if __name__ == '__main__':
    sys.exit(run_exp('JRA55_RYF'))

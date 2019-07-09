
import os
import f90nml
import json
import ast
import pytest
import datetime
import dateutil.parser
from collections import OrderedDict
from helper import Helper

class LogItem:

    def __init__(self, field_name, field_file,
                 field_index, forcing_datetime, checksum):
        self.forcing_datetime = forcing_datetime
        self.field_name = field_name
        self.field_file = field_file
        self.field_index = field_index
        self.checksum = checksum


def extract_field_name(checksum):
    k = list(checksum.keys())
    assert len(k) == 1
    k = k[0]

    return k.split('-')[2]

def dicts_to_list(key_name, log_str):
    lines = filter(lambda x : key_name in x, log_str.splitlines())
    out = []
    for l in lines:
        out += list(ast.literal_eval(l.strip()).values())
    return out


def build_log_items(log_str):

    forcing_update_dts = dicts_to_list('forcing_update_field-datetime', log_str)
    forcing_update_dts = [dateutil.parser.parse(d) for d in forcing_update_dts]
    field_update_files = dicts_to_list('field_update_data-file', log_str)
    field_update_indices = dicts_to_list('field_update_data-index', log_str)

    tmp_chk = filter(lambda x : 'checksum' in x, log_str.splitlines())
    checksums = []
    for c in tmp_chk:
        checksums.append(ast.literal_eval(c.strip()))

    log_items = []

    # Remove duplicate runoff checksums
    checksums, num_removed = remove_duplicate_runoff_checksums(checksums)

    assert len(forcing_update_dts) == len(field_update_files) == \
                len(field_update_indices) == len(checksums)

    field_names = set()
    for i in range(len(forcing_update_dts)):
        field_name = extract_field_name(checksums[i])
        field_names.add(field_name)
        item = LogItem(field_name, field_update_files[i],
                       field_update_indices[i], forcing_update_dts[i],
                       checksums[i])
        log_items.append(item)

    cur_exp_dts = dicts_to_list('cur_exp-datetime', log_str)
    cur_exp_dts = [dateutil.parser.parse(d) for d in cur_exp_dts]
    cur_forcing_dts = dicts_to_list('cur_forcing-datetime', log_str)
    cur_forcing_dts = [dateutil.parser.parse(d) for d in cur_forcing_dts]

    # There should be one cur_exp_dts and cur_forcing_dts for each exchange of
    # all fields
    assert len(cur_exp_dts) == len(cur_forcing_dts) == \
            (len(forcing_update_dts) // len(field_names))

    return log_items

def remove_duplicate_runoff_checksums(checksums):

    new_checksums = []
    found_runoff_checksums = []
    num_removed_runoff_checksums = 0

    for c in checksums:
        k = list(c.keys())
        v = list(c.values())
        assert len(k) == 1
        if 'runof_ai' in k[0]:
            if v[0] not in found_runoff_checksums:
                new_checksums.append(c)
                found_runoff_checksums.append(v[0])
            else:
                num_removed_runoff_checksums += 1
        else:
            new_checksums.append(c)

    return new_checksums, num_removed_runoff_checksums

@pytest.fixture
def helper():
    return Helper()

@pytest.fixture(params=['JRA55_IAF', 'JRA55_RYF', 'JRA55_RYF_MINIMAL'])
def exp(request):
    yield request.param

@pytest.fixture(params=['JRA55_IAF_SINGLE_FIELD'])
def exp_fast(request):
    yield request.param


class TestStubs:

    @pytest.mark.fast
    def test_run(self, helper, exp):
        """
        Check that the default configurations run.
        """

        ret, output, log, matm_log = helper.run_exp(exp)
        assert ret == 0


    def test_unchanged_forcing_checksums(self, helper, exp):
        """
        Test that checksums have not changed.
        """

        ret, output, log, matm_log = helper.run_exp(exp)
        assert ret == 0

        run_checksums = helper.filter_checksums(log)
        stored_checksums = helper.checksums(exp)

        # Check that keys are the same
        assert set(run_checksums.keys()) == set(stored_checksums.keys())
        # Check that everything is the same
        assert run_checksums == stored_checksums


    @pytest.mark.scaling
    def test_field_scaling(self, helper):
        ret, output, log, matm_log = helper.run_exp('FORCING_SCALING')
        assert ret == 0

        run_checksums = helper.filter_checksums(log)
        stored_checksums = helper.checksums('FORCING_SCALING')

        # FIXME: don't hard-code this, calculate that times/keys are correct.
        keys = ['checksum-matmxx-swfld_ai-0000043200',
                'checksum-matmxx-swfld_ai-0000054000',
                'checksum-matmxx-swfld_ai-0000064800',
                'checksum-matmxx-swfld_ai-0000075600']

        # Scaling multiplied by 0, 1, 2, 3
        for mult, k in enumerate(keys):
            assert abs(run_checksums[k] - mult*stored_checksums[k]) < 0.1

    @pytest.mark.slow
    def test_forcing_fields(self, helper, exp):
        """
        Check that dates and checksums from YATM match those calculated here
        """

        ret, output, log, matm_log = helper.run_exp(exp)
        assert ret == 0

        log_items = build_log_items(log)

        # Get the experiment start and end dates
        exp_dir = os.path.join(helper.test_dir, exp)
        accessom2_config = os.path.join(exp_dir, 'accessom2.nml')
        with open(accessom2_config) as f:
            nml = f90nml.read(f)
            forcing_start_date = nml['date_manager_nml']['forcing_start_date']
            forcing_end_date = nml['date_manager_nml']['forcing_end_date']
            forcing_start_date = dateutil.parser.parse(forcing_start_date)
            forcing_end_date = dateutil.parser.parse(forcing_end_date)

        # Parse forcing.json
        forcing_config = os.path.join(exp_dir, 'forcing.json')
        with open(forcing_config) as f:
            forcing = json.load(f)

        # Check that first forcing time corrosponds to forcing_start_date
        assert log_items[0].forcing_datetime == forcing_start_date 

        # Check that field dt is all the same and as expected 
        uniq_dt = list(OrderedDict.fromkeys(forcing_update_dts))
        dt = [b - a for a, b in zip(uniq_dt, uniq_dt[1:])]
        assert set(dt).pop() == datetime.timedelta(hours=3)

        # Check that indices for a particular year are sequential and increasing

        # Check that we have the right numbers of duplicate indices, i.e. all
        # forcing fields have the same indices except for runoff

        # Check that indices go back to 0 when crossing a year boundary

        # Iterate over forcing in Python, check that Fortran code did the same
        # by comparing the checksums of each field.


    def test_restart(self, helper, exp):
        """
        Test that model restarts at the correct date.
        """
        pass

    @pytest.mark.very_slow
    def test_iaf_cycles(self, helper, exp_fast):
        """
        Test that experiment and forcing dates are always in sync.

        Esp relevant for multi-cycle IAF run, see:
        https://github.com/COSIMA/access-om2/issues/149
        """

        ret, output, log, matm_log = helper.run_exp(exp_fast, years_duration=1)

        log_items = build_log_items(log)
        # Check that experiment and forcing dates only differ as expected.

        assert ret == 0


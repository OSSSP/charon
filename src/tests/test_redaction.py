import unittest
import json
import os
import pytest
import base64

from eve import Eve
from pymongo import MongoClient
from auth import check_insert_access, check_insert_data_context, CharonAuth
from aggregators import add_ascl_redaction

MONGO_DBNAME = 'dbz-mongo-test'
MONGO_HOST = '127.0.0.1'

US_CITIZEN_DISS = ['usg_noforn', 'usg_relfvey', 'usg_relgbr']
GBR_CITIZEN_DISS = ['usg_relfvey', 'usg_relgbr']
CAN_CITIZEN_DISS = ['usg_relfvey']


@pytest.fixture(scope='module', autouse=True)
def setup_fee_db():
    client = MongoClient(MONGO_HOST, 27017)
    db = client[MONGO_DBNAME]
    fee_collection = db['fees']

    already_populated = fee_collection.count_documents({}) > 0

    if not already_populated:
        print('\n\npopulating db\n\n')
        current_path = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(current_path, 'fixtures/fee_charges_sec.json')

        with open(path) as f:
            file_data = json.load(f)

        fee_collection.insert_many(file_data)
        client.close()
    else:
        print('\n\ndb is already populated\n\n')


@pytest.fixture(scope='module', autouse=True)
def setup_users():
    client = MongoClient(MONGO_HOST, 27017)
    db = client['admin']
    user_collection = db['charon_user_permissions']

    already_populated = user_collection.count_documents({}) > 0

    if not already_populated:
        current_path = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(current_path, 'fixtures/users.json')

        with open(path) as f:
            file_data = json.load(f)

        user_collection.insert_many(file_data)
        client.close()


def make_headers(username, password):
    """Add standard headers - Basic Authorization and JSON content type. Pass auth string as decoded base64."""
    cred_str = '{}:{}'.format(username, password).encode('utf-8')
    creds = base64.b64encode(cred_str).decode('utf-8')
    headers = {'Content-Type': 'application/json',
               'Authorization': 'Basic {}'.format(creds)}
    return headers


class BasicTestCase(unittest.TestCase):
    def assert_cat_list(self, items, sec_list):
        """Asserts that security category listed in the db item is allowed for the user."""
        for item in items:
            if item.get('_sec').get('cat') not in sec_list:
                self.fail('Received document with forbidden security category: {}'.format(item.get('_sec').get('cat')))

    def assert_dist_list(self, items, dist_list):
        """Asserts that all dissemination controls listed in the db item are allowed for the user."""
        user_diss_set = set(dist_list)
        for item in items:
            item_diss_set = set(item.get('_sec').get('diss'))
            if not item_diss_set.issubset(user_diss_set):
                self.fail('Received document with forbidden distribution rule: {}'.format(item_diss_set))
        return True

    def setUp(self):
        """Define test variables and initialize app."""
        test_settings = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'settings.py')

        # Set Schema
        os.environ['TEST_SCHEMA'] = '{"fees": {"Block": {"type": "string"},"Boro": {"type": "string"},"BoroID": {"type": "string"},"BuildingID": {"type": "string"},"DoFAccountType": {"type": "string"},"DoFTransferDate": {"type": "string"},"FeeAmount": {"type": "string"},"FeeID": {"type": "string"},"FeeIssuedDate": {"type": "string"},"FeeSourceID": {"type": "string"},"FeeSourceType": {"type": "string"},"FeeSourceTypeID": {"type": "string"},"FeeType": {"type": "string"},"FeeTypeID": {"type": "string"},"HouseNumber": {"type": "string"},"LifeCycle": {"type": "string"},"Lot": {"type": "string"},"StreetName": {"type": "string"},"Zip": {"type": "string"},"_sec": {"schema": {"cat": {"type": "string"},"diss": {"schema": {"type": "string"},"type": "list"}},"type": "dict"},"attachments": {"schema": {"_sec": {"schema": {"cat": {"type": "string"},"diss": {"schema": {"type": "string"},"type": "list"}},"type": "dict"},"documents": {"type": "list"}},"type": "dict"},"vars": {}},"fees_nested": {"Block": {"type": "string"},"Boro": {"type": "string"},"BoroID": {"type": "string"},"BuildingID": {"type": "string"},"DoFAccountType": {"type": "string"},"DoFTransferDate": {"type": "string"},"FeeAmount": {"type": "string"},"FeeID": {"schema": {"_sec": {"schema": {"cat": {"type": "string"},"diss": {"schema": {"type": "string"},"type": "list"}},"type": "dict"},"value": {"type": "string"}},"type": "dict"},"FeeIssuedDate": {"type": "string"},"FeeSourceID": {"type": "string"},"FeeSourceType": {"type": "string"},"FeeSourceTypeID": {"type": "string"},"FeeType": {"type": "string"},"FeeTypeID": {"type": "string"},"HouseNumber": {"type": "string"},"LifeCycle": {"type": "string"},"Lot": {"type": "string"},"StreetName": {"type": "string"},"Zip": {"type": "string"},"_sec": {"schema": {"cat": {"type": "string"},"diss": {"schema": {"type": "string"},"type": "list"}},"type": "dict"},"vars": {}}}'

        self.app = Eve(settings=test_settings, auth=CharonAuth)
        self.app.config['TESTING'] = True
        self.app.config['DEBUG'] = True
        self.app.config['MONGO_DBNAME'] = MONGO_DBNAME
        self.app.config['MONGO_HOST'] = MONGO_HOST

        self.app.on_pre_POST += check_insert_data_context
        self.app.on_pre_POST += check_insert_access

        self.app.before_aggregation += add_ascl_redaction
        self.client = self.app.test_client()
        self.app.testing = True
    #
    # US Citizens
    #

    def test_user_ctx_us_unclassified(self):
        """Test redaction for a user with cat == unclassified and US citizen dissemination rights."""
        headers = make_headers('us_unclassified_only', 'password')

        res = self.client.get('/fees', headers=headers)

        self.assertEqual(res.status_code, 200)
        resp_data = None
        try:
            resp_data = json.loads(res.data)
        except json.decoder.JSONDecodeError as exc:
            self.fail('Received invalid json from /fees: {}'.format(exc))

        self.assert_cat_list(resp_data.get('_items'), ['usg_unclassified'])
        self.assert_dist_list(resp_data.get('_items'), US_CITIZEN_DISS)
        # self.assertEqual(len(resp_data.get('_items')), 0)

    def test_user_ctx_us_confidential_only(self):
        """Test redaction for a user with cat == confidential and US citizen dissemination rights."""
        headers = make_headers('us_confidential_only', 'password')

        res = self.client.get('/fees', headers=headers)

        self.assertEqual(res.status_code, 200)
        resp_data = None
        try:
            resp_data = json.loads(res.data)
        except json.decoder.JSONDecodeError as exc:
            self.fail('Received invalid json from /fees: {}'.format(exc))

        self.assert_cat_list(resp_data.get('_items'), ['usg_confidential'])
        self.assert_dist_list(resp_data.get('_items'), US_CITIZEN_DISS)
        # self.assertEqual(len(resp_data.get('_items')), 35141)

    def test_user_ctx_us_secret_cumul(self):
        """Test redaction for a user with cat == secret and US citizen dissemination rights."""
        headers = make_headers('us_secret_cumul', 'password')

        res = self.client.get('/fees', headers=headers)

        self.assertEqual(res.status_code, 200)
        resp_data = None
        try:
            resp_data = json.loads(res.data)
        except json.decoder.JSONDecodeError as exc:
            self.fail('Received invalid json from /fees: {}'.format(exc))

        self.assert_cat_list(resp_data.get('_items'), ['usg_unclassified', 'usg_confidential', 'usg_secret'])
        self.assert_dist_list(resp_data.get('_items'), US_CITIZEN_DISS)
        # self.assertEqual(len(resp_data.get('_items')), 37649)

    def test_user_ctx_us_topsecret_cumul(self):
        """Test redaction for a user with cat == topsecret and US citizen dissemination rights."""
        headers = make_headers('us_topsecret_cumul', 'password')

        res = self.client.get('/fees', headers=headers)

        self.assertEqual(res.status_code, 200)
        resp_data = None
        try:
            resp_data = json.loads(res.data)
        except json.decoder.JSONDecodeError as exc:
            self.fail('Received invalid json from /fees: {}'.format(exc))

        self.assert_cat_list(resp_data.get('_items'), ['usg_unclassified', 'usg_confidential', 'usg_secret', 'usg_topsecret'])
        self.assert_dist_list(resp_data.get('_items'), US_CITIZEN_DISS)
        # self.assertEqual(len(resp_data.get('_items')), 37961)

    def test_user_ctx_us_topsecret_only(self):
        """Test redaction for a user with cat == topsecret ONLY and US citizen dissemination rights."""
        headers = make_headers('us_topsecret_only', 'password')

        res = self.client.get('/fees', headers=headers)

        self.assertEqual(res.status_code, 200)
        resp_data = None
        try:
            resp_data = json.loads(res.data)
        except json.decoder.JSONDecodeError as exc:
            self.fail('Received invalid json from /fees: {}'.format(exc))

        self.assert_cat_list(resp_data.get('_items'), ['usg_topsecret'])
        self.assert_dist_list(resp_data.get('_items'), US_CITIZEN_DISS)
        # self.assertEqual(len(resp_data.get('_items')), 312)

    def test_user_ctx_us_secret_only(self):
        """Test redaction for a user with cat == secret ONLY and US citizen dissemination rights."""
        headers = make_headers('us_secret_only', 'password')

        res = self.client.get('/fees', headers=headers)

        self.assertEqual(res.status_code, 200)
        resp_data = None
        try:
            resp_data = json.loads(res.data)
        except json.decoder.JSONDecodeError as exc:
            self.fail('Received invalid json from /fees: {}'.format(exc))

        self.assert_cat_list(resp_data.get('_items'), ['usg_secret'])
        self.assert_dist_list(resp_data.get('_items'), US_CITIZEN_DISS)
        # self.assertEqual(len(resp_data.get('_items')), 2508)

    # #
    # # CAN Citizens (or AUS, or NZL)
    # #

    def test_user_ctx_can_unclassified(self):
        """Test redaction for a user with cat == unclassified and CAN citizen dissemination rights."""
        headers = make_headers('can_unclassified_only', 'password')

        res = self.client.get('/fees', headers=headers)

        self.assertEqual(res.status_code, 200)
        resp_data = None
        try:
            resp_data = json.loads(res.data)
        except json.decoder.JSONDecodeError as exc:
            self.fail('Received invalid json from /fees: {}'.format(exc))

        self.assert_cat_list(resp_data.get('_items'), ['usg_unclassified'])
        self.assert_dist_list(resp_data.get('_items'), CAN_CITIZEN_DISS)
        # self.assertEqual(len(resp_data.get('_items')), 0)

    def test_user_ctx_can_confidential_only(self):
        """Test redaction for a user with cat == confidential and CAN citizen dissemination rights."""
        headers = make_headers('can_confidential_only', 'password')

        res = self.client.get('/fees', headers=headers)

        self.assertEqual(res.status_code, 200)
        resp_data = None
        try:
            resp_data = json.loads(res.data)
        except json.decoder.JSONDecodeError as exc:
            self.fail('Received invalid json from /fees: {}'.format(exc))

        self.assert_cat_list(resp_data.get('_items'), ['usg_unclassified', 'usg_confidential'])
        self.assert_dist_list(resp_data.get('_items'), CAN_CITIZEN_DISS)
        # self.assertEqual(len(resp_data.get('_items')), 1541)

    def test_user_ctx_can_secret_cumul(self):
        """Test redaction for a user with cat == secret and CAN citizen dissemination rights."""
        headers = make_headers('can_secret_cumul', 'password')

        res = self.client.get('/fees', headers=headers)

        self.assertEqual(res.status_code, 200)
        resp_data = None
        try:
            resp_data = json.loads(res.data)
        except json.decoder.JSONDecodeError as exc:
            self.fail('Received invalid json from /fees: {}'.format(exc))

        self.assert_cat_list(resp_data.get('_items'), ['usg_unclassified', 'usg_confidential', 'usg_secret'])
        self.assert_dist_list(resp_data.get('_items'), CAN_CITIZEN_DISS)
        # self.assertEqual(len(resp_data.get('_items')), 1698)

    def test_user_ctx_can_topsecret_cumul(self):
        """Test redaction for a user with cat == topsecret and CAN citizen dissemination rights."""
        headers = make_headers('can_topsecret_cumul', 'password')

        res = self.client.get('/fees', headers=headers)

        self.assertEqual(res.status_code, 200)
        resp_data = None
        try:
            resp_data = json.loads(res.data)
        except json.decoder.JSONDecodeError as exc:
            self.fail('Received invalid json from /fees: {}'.format(exc))

        self.assert_cat_list(resp_data.get('_items'), ['usg_unclassified', 'usg_confidential', 'usg_secret', 'usg_topsecret'])
        self.assert_dist_list(resp_data.get('_items'), CAN_CITIZEN_DISS)
        # self.assertEqual(len(resp_data.get('_items')), 1738)

    def test_user_ctx_can_secret_only(self):
        """Test redaction for a user with cat == secret ONLY and CAN citizen dissemination rights."""
        headers = make_headers('can_secret_only', 'password')

        res = self.client.get('/fees', headers=headers)

        self.assertEqual(res.status_code, 200)
        resp_data = None
        try:
            resp_data = json.loads(res.data)
        except json.decoder.JSONDecodeError as exc:
            self.fail('Received invalid json from /fees: {}'.format(exc))

        self.assert_cat_list(resp_data.get('_items'), ['usg_secret'])
        self.assert_dist_list(resp_data.get('_items'), CAN_CITIZEN_DISS)
        # self.assertEqual(len(resp_data.get('_items')), 157)

    def test_user_ctx_can_topsecret_only(self):
        """Test redaction for a user with cat == topsecret ONLY and CAN citizen dissemination rights."""
        headers = make_headers('can_topsecret_only', 'password')

        res = self.client.get('/fees', headers=headers)

        self.assertEqual(res.status_code, 200)
        resp_data = None
        try:
            resp_data = json.loads(res.data)
        except json.decoder.JSONDecodeError as exc:
            self.fail('Received invalid json from /fees: {}'.format(exc))

        self.assert_cat_list(resp_data.get('_items'), ['usg_topsecret'])
        self.assert_dist_list(resp_data.get('_items'), CAN_CITIZEN_DISS)
        # self.assertEqual(len(resp_data.get('_items')), 40)

    # #
    # # GBR Citizens
    # #

    def test_user_ctx_gbr_unclassified(self):
        """Test redaction for a user with cat == unclassified and GBR citizen dissemination rights."""
        headers = make_headers('gbr_unclassified_only', 'password')

        res = self.client.get('/fees', headers=headers)

        self.assertEqual(res.status_code, 200)
        resp_data = None
        try:
            resp_data = json.loads(res.data)
        except json.decoder.JSONDecodeError as exc:
            self.fail('Received invalid json from /fees: {}'.format(exc))

        self.assert_cat_list(resp_data.get('_items'), ['usg_unclassified'])
        self.assert_dist_list(resp_data.get('_items'), GBR_CITIZEN_DISS)
        # self.assertEqual(len(resp_data.get('_items')), 0)

    def test_user_ctx_gbr_confidential_only(self):
        """Test redaction for a user with cat == confidential and GBR citizen dissemination rights."""
        headers = make_headers('gbr_confidential_only', 'password')

        res = self.client.get('/fees', headers=headers)

        self.assertEqual(res.status_code, 200)
        resp_data = None
        try:
            resp_data = json.loads(res.data)
        except json.decoder.JSONDecodeError as exc:
            self.fail('Received invalid json from /fees: {}'.format(exc))

        for item in resp_data.get('_items'):
            if "usg_noforn" in item.get('_sec').get('diss') > 0:
                self.fail('Got a document marked "usg_noforn" for a GBR citizen.')
            if "usg_fouo" in item.get('_sec').get('diss') > 0:
                self.fail('Got a document marked "usg_fouo" for a GBR citizen.')
            # Check numbers in the test document
            if item.get('BoroID') in [1, 4]:
                self.fail('BoroID is in [1,4], this should indicate a usg_noforn designation.')

        self.assert_cat_list(resp_data.get('_items'), ['usg_confidential'])
        self.assert_dist_list(resp_data.get('_items'), GBR_CITIZEN_DISS)
        # self.assertEqual(len(resp_data.get('_items')), 15507)

    def test_user_ctx_gbr_secret_cumul(self):
        """Test redaction for a user with cat == secret and GBR citizen dissemination rights."""
        headers = make_headers('gbr_secret_cumul', 'password')

        res = self.client.get('/fees', headers=headers)

        self.assertEqual(res.status_code, 200)
        resp_data = None
        try:
            resp_data = json.loads(res.data)
        except json.decoder.JSONDecodeError as exc:
            self.fail('Received invalid json from /fees: {}'.format(exc))

        self.assert_cat_list(resp_data.get('_items'), ['usg_unclassified', 'usg_confidential', 'usg_secret'])
        self.assert_dist_list(resp_data.get('_items'), GBR_CITIZEN_DISS)
        # self.assertEqual(len(resp_data.get('_items')), 15664)

    def test_user_ctx_gbr_topsecret_cumul(self):
        """Test redaction for a user with cat == topsecret and GBR citizen dissemination rights."""
        headers = make_headers('gbr_topsecret_cumul', 'password')

        res = self.client.get('/fees', headers=headers)

        self.assertEqual(res.status_code, 200)
        resp_data = None
        try:
            resp_data = json.loads(res.data)
        except json.decoder.JSONDecodeError as exc:
            self.fail('Received invalid json from /fees: {}'.format(exc))

        self.assert_cat_list(resp_data.get('_items'), ['usg_unclassified', 'usg_confidential', 'usg_secret', 'usg_topsecret'])
        self.assert_dist_list(resp_data.get('_items'), GBR_CITIZEN_DISS)
        # self.assertEqual(len(resp_data.get('_items')), 15704)

    def test_user_ctx_gbr_secret_only(self):
        """Test redaction for a user with cat == secret ONLY and GBR citizen dissemination rights."""
        headers = make_headers('gbr_secret_only', 'password')

        res = self.client.get('/fees', headers=headers)

        self.assertEqual(res.status_code, 200)
        resp_data = None
        try:
            resp_data = json.loads(res.data)
        except json.decoder.JSONDecodeError as exc:
            self.fail('Received invalid json from /fees: {}'.format(exc))

        self.assert_cat_list(resp_data.get('_items'), ['usg_secret'])
        self.assert_dist_list(resp_data.get('_items'), GBR_CITIZEN_DISS)
        # self.assertEqual(len(resp_data.get('_items')), 157)

    def test_user_ctx_gbr_topsecret_only(self):
        """Test redaction for a user with cat == topsecret ONLY and GBR citizen dissemination rights."""
        headers = make_headers('gbr_topsecret_only', 'password')

        res = self.client.get('/fees', headers=headers)

        self.assertEqual(res.status_code, 200)
        resp_data = None
        try:
            resp_data = json.loads(res.data)
        except json.decoder.JSONDecodeError as exc:
            self.fail('Received invalid json from /fees: {}'.format(exc))

        self.assert_cat_list(resp_data.get('_items'), ['usg_topsecret'])
        self.assert_dist_list(resp_data.get('_items'), GBR_CITIZEN_DISS)
        # self.assertEqual(len(resp_data.get('_items')), 40)

    def test_secret_insert_user_us_unclassified(self):
        """Test redaction for a user with cat == unclassified and US citizen dissemination rights."""
        headers = make_headers('us_unclassified_only', 'password')

        data = {
            'FeeID': '471',
            'BuildingID': '306039',
            'BoroID': '3',
            'Boro': 'BROOKLYN',
            'HouseNumber': '312',
            'StreetName': 'MACON STREET',
            'Zip': '11233',
            'Block': '569',
            'Lot': '3',
            'LifeCycle': 'Building',
            'FeeTypeID': '1',
            'FeeType': 'Initial Re-inspection Fee',
            'FeeSourceTypeID': '51',
            'FeeSourceType': 'PROJECT BLDG',
            'FeeSourceID': '30305',
            'FeeIssuedDate': '2019-09-02T00:00:00',
            'FeeAmount': '3000.00',
            'DoFAccountType': '236',
            'DoFTransferDate': '2019-10-20T00:00:00',
            "attachments": {"_sec": {"cat": "usg_unclassified", "diss": []}, "documents": []},
            '_sec': {'cat': 'usg_secret', 'diss': []}
        }

        res = self.client.post('/fees_write', data=json.dumps(data), headers=headers)

        self.assertEqual(res.status_code, 403)

    def test_secret_insert_user_us_secret(self):
        """Test redaction for a user with cat == unclassified and US citizen dissemination rights."""
        headers = make_headers('us_secret_cumul', 'password')

        data = {
            'FeeID': '471',
            'BuildingID': '306039',
            'BoroID': '3',
            'Boro': 'BROOKLYN',
            'HouseNumber': '312',
            'StreetName': 'MACON STREET',
            'Zip': '11233',
            'Block': '569',
            'Lot': '3',
            'LifeCycle': 'Building',
            'FeeTypeID': '1',
            'FeeType': 'Initial Re-inspection Fee',
            'FeeSourceTypeID': '51',
            'FeeSourceType': 'PROJECT BLDG',
            'FeeSourceID': '30305',
            'FeeIssuedDate': '2019-09-02T00:00:00',
            'FeeAmount': '3000.00',
            'DoFAccountType': '236',
            'DoFTransferDate': '2019-10-20T00:00:00',
            "attachments": {"_sec": {"cat": "usg_unclassified", "diss": []}, "documents": []},
            '_sec': {'cat': 'usg_secret', 'diss': []}
        }

        res = self.client.post('/fees_write', data=json.dumps(data), headers=headers)

        self.assertEqual(res.status_code, 201)

    def test_secret_nested_insert_user_us_unclassified(self):
        """Test redaction for a user with cat == unclassified and US citizen dissemination rights."""
        headers = make_headers('us_unclassified_only', 'password')

        data = {
            'FeeID': {
                'value': '471',
                '_sec': {'cat': 'usg_secret', 'diss': ['usg_noforn', 'usg_fouo']}
            },
            'BuildingID': '306039',
            'BoroID': '3',
            'Boro': 'BROOKLYN',
            'HouseNumber': '312',
            'StreetName': 'MACON STREET',
            'Zip': '11233',
            'Block': '569',
            'Lot': '3',
            'LifeCycle': 'Building',
            'FeeTypeID': '1',
            'FeeType': 'Initial Re-inspection Fee',
            'FeeSourceTypeID': '51',
            'FeeSourceType': 'PROJECT BLDG',
            'FeeSourceID': '30305',
            'FeeIssuedDate': '2019-09-02T00:00:00',
            'FeeAmount': '3000.00',
            'DoFAccountType': '236',
            'DoFTransferDate': '2019-10-20T00:00:00',
            '_sec': {'cat': 'usg_secret', 'diss': []}
        }

        res = self.client.post('/fees_nested_write', data=json.dumps(data), headers=headers)

        self.assertEqual(res.status_code, 403)

    def test_secret_nested_insert_user_us_secret(self):
        """Test redaction for a user with cat == unclassified and US citizen dissemination rights."""
        headers = make_headers('us_secret_cumul', 'password')

        data = {
            'FeeID': {
                'value': '471',
                '_sec': {'cat': 'usg_secret', 'diss': ['usg_noforn']}
            },
            'BuildingID': '306039',
            'BoroID': '3',
            'Boro': 'BROOKLYN',
            'HouseNumber': '312',
            'StreetName': 'MACON STREET',
            'Zip': '11233',
            'Block': '569',
            'Lot': '3',
            'LifeCycle': 'Building',
            'FeeTypeID': '1',
            'FeeType': 'Initial Re-inspection Fee',
            'FeeSourceTypeID': '51',
            'FeeSourceType': 'PROJECT BLDG',
            'FeeSourceID': '30305',
            'FeeIssuedDate': '2019-09-02T00:00:00',
            'FeeAmount': '3000.00',
            'DoFAccountType': '236',
            'DoFTransferDate': '2019-10-20T00:00:00',
            '_sec': {'cat': 'usg_secret', 'diss': []}
        }

        res = self.client.post('/fees_nested_write', data=json.dumps(data), headers=headers)

        self.assertEqual(res.status_code, 201)

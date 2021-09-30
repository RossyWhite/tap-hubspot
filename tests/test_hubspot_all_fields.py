import tap_tester.connections as connections
import tap_tester.menagerie   as menagerie
import tap_tester.runner      as runner
import datetime
from base import HubspotBaseTest
from client import TestClient

KNOWN_EXTRA_FIELDS = {
    'deals': {
        # BUG_TDL-14993 | https://jira.talendforge.org/browse/TDL-14993
        #                 Has an value of object with key 'value' and value 'Null'
        'property_hs_date_entered_1258834',
    },
}

KNOWN_MISSING_FIELDS = {
    'contact_lists': {  # BUG https://jira.talendforge.org/browse/TDL-14996
        'authorId',
        'teamIds'
    },
    'email_events': {  # BUG https://jira.talendforge.org/browse/TDL-14997
        'portalSubscriptionStatus',
        'attempt',
        'source',
        'subscriptions',
        'sourceId',
        'replyTo',
        'suppressedMessage',
        'bcc',
        'suppressedReason',
        'cc',
     },
    'workflows': {  # BUG https://jira.talendforge.org/browse/TDL-14998
        'migrationStatus',
        'updateSource',
        'description',
        'originalAuthorUserId',
        'lastUpdatedByUserId',
        'creationSource',
        'portalId',
        'contactCounts',
    },
    'owners': {  # BUG https://jira.talendforge.org/browse/TDL-15000
        'activeSalesforceId'
    },
    'forms': {  # BUG https://jira.talendforge.org/browse/TDL-15001
        'alwaysCreateNewCompany',
        'themeColor',
        'publishAt',
        'editVersion',
        'themeName',
        'style',
        'thankYouMessageJson',
        'createMarketableContact',
        'kickbackEmailWorkflowId',
        'businessUnitId',
        'portableKey',
        'parentId',
        'kickbackEmailsJson',
        'unpublishAt',
        'internalUpdatedAt',
        'multivariateTest',
        'publishedAt',
        'customUid',
        'isPublished',
    },
    'companies': {  # BUG https://jira.talendforge.org/browse/TDL-15003
        'mergeAudits',
        'stateChanges',
        'isDeleted',
        'additionalDomains',
    },
    'campaigns': {  # BUG https://jira.talendforge.org/browse/TDL-15003
        'lastProcessingStateChangeAt',
        'lastProcessingFinishedAt',
        'processingState',
        'lastProcessingStartedAt',
    },
    'deals': {  # BUG https://jira.talendforge.org/browse/TDL-14999
        'imports',
        'property_hs_num_associated_deal_splits',
        'property_hs_is_deal_split',
        'stateChanges',
        'property_hs_num_associated_active_deal_registrations',
        'property_hs_num_associated_deal_registrations'
    },
    'subscription_changes':{
        'normalizedEmailId'
    }
}

class TestHubspotAllFields(HubspotBaseTest):
    """Test that with all fields selected for a stream we replicate data as expected"""

    def name(self):
        return "tt_all_fields_dynamic_data_test"

    def streams_under_test(self):
        """expected streams minus the streams not under test"""
        return self.expected_streams().difference({
            'contacts_by_company', # TODO Failing with missing expected records in sync
            'owners',
            'subscription_changes', # BUG_TDL-14938 https://jira.talendforge.org/browse/TDL-14938
        })

    def setUp(self):
        self.maxDiff = None  # see all output in failure

        # TODO use the read method
        test_client = TestClient(start_date=self.get_properties()['start_date'])
        self.expected_records = dict()
        streams = self.streams_under_test()
        stream_to_run_last = 'contacts_by_company'
        if stream_to_run_last in streams:
            streams.remove(stream_to_run_last)
            streams = list(streams)
            streams.append(stream_to_run_last)

        for stream in streams:
            # Get all records
            if stream == 'contacts_by_company':
                company_ids = [company['companyId'] for company in self.expected_records['companies']]
                self.expected_records[stream] = test_client.read(stream, parent_ids=company_ids)
            elif stream in {'companies', 'contact_lists', 'subscription_changes', 'engagements'}:
                self.expected_records[stream] = test_client.read(stream)
            else:
                self.expected_records[stream] = test_client.read(stream)

        for stream, records in self.expected_records.items():
            print(f"The test client found {len(records)} {stream} records.")


        self.convert_datatype(self.expected_records)

    def convert_datatype(self, expected_records):
        for stream, records in expected_records.items():
            for record in records:

                # convert timestamps to string formatted datetime
                timestamp_keys = {'timestamp'}
                for key in timestamp_keys:
                    timestamp = record.get(key)
                    if timestamp:
                        unformatted = datetime.datetime.fromtimestamp(timestamp/1000)
                        formatted = datetime.datetime.strftime(unformatted, self.BASIC_DATE_FORMAT)
                        record[key] = formatted

        return expected_records
    def test_run(self):
        conn_id = connections.ensure_connection(self)

        found_catalogs = self.run_and_verify_check_mode(conn_id)

        # Select only the expected streams tables
        expected_streams = self.streams_under_test()
        catalog_entries = [ce for ce in found_catalogs if ce['tap_stream_id'] in expected_streams]
        for catalog_entry in catalog_entries:
            stream_schema = menagerie.get_annotated_schema(conn_id, catalog_entry['stream_id'])
            connections.select_catalog_and_fields_via_metadata(
                conn_id,
                catalog_entry,
                stream_schema
            )

        # Run sync
        first_record_count_by_stream = self.run_and_verify_sync(conn_id)
        synced_records = runner.get_records_from_target_output()

        # Test by Stream
        for stream in expected_streams:
            with self.subTest(stream=stream):

                # gather expected values
                replication_method = self.expected_replication_method()[stream]
                primary_keys = self.expected_primary_keys()[stream]

                # gather replicated records
                actual_records = [message['data']
                                  for message in synced_records[stream]['messages']
                                  if message['action'] == 'upsert']

                for expected_record in self.expected_records[stream]:

                    primary_key_dict = {primary_key: expected_record[primary_key] for primary_key in primary_keys}
                    primary_key_values = list(primary_key_dict.values())

                    with self.subTest(expected_record=primary_key_dict):

                        # grab the replicated record that corresponds to expected_record by checking primary keys
                        matching_actual_records_by_pk = [record for record in actual_records
                                                         if primary_key_values == [record[primary_key]
                                                                                   for primary_key in primary_keys]]
                        self.assertEqual(1, len(matching_actual_records_by_pk))
                        actual_record = matching_actual_records_by_pk[0]


                        # NB: KNOWN_MISSING_FIELDS is a dictionary of streams to aggregated missing fields.
                        #     We will check each expected_record to see which of the known keys is present in expectations
                        #     and then will add them to the known_missing_keys set.
                        known_missing_keys = set()
                        for missing_key in KNOWN_MISSING_FIELDS.get(stream, set()):
                            if missing_key in expected_record.keys():
                                known_missing_keys.add(missing_key)

                        # NB : KNOWN_EXTRA_FIELDS is a dictionary of streams to fields that should not
                        #      be replicated but are. See the variable declaration at top of file for linked BUGs.
                        known_extra_keys = set()
                        for extra_key in KNOWN_EXTRA_FIELDS.get(stream, set()):
                            known_extra_keys.add(extra_key)


                        # Verify the fields in our expected record match the fields in the corresponding replicated record
                        expected_keys_adjusted = set(expected_record.keys()).union(known_extra_keys)
                        actual_keys_adjusted = set(actual_record.keys()).union(known_missing_keys)
                        # TODO There are dynamic fields on here that we just can't track.
                        #      But shouldn't we be doing dynamic field discovery on these things? BUG?
                        # deals workaround for 'property_hs_date_entered_<property>' fields
                        bad_key_prefixes = {'property_hs_date_entered_', 'property_hs_date_exited_'}
                        bad_keys = set()
                        for key in expected_keys_adjusted:
                            for prefix in bad_key_prefixes:
                                if key.startswith(prefix) and key not in actual_keys_adjusted:
                                    bad_keys.add(key)
                        for key in actual_keys_adjusted:
                            for prefix in bad_key_prefixes:
                                if key.startswith(prefix) and key not in expected_keys_adjusted:
                                    bad_keys.add(key)
                        for key in bad_keys:
                            if key in expected_keys_adjusted:
                                expected_keys_adjusted.remove(key)
                            elif key in actual_keys_adjusted:
                                actual_keys_adjusted.remove(key)

                        self.assertSetEqual(expected_keys_adjusted, actual_keys_adjusted)

                # Verify by primary key values that only the expected records were replicated
                expected_primary_key_values = {tuple([record[primary_key]
                                                      for primary_key in primary_keys])
                                               for record in self.expected_records[stream]}
                actual_records_primary_key_values = {tuple([record[primary_key]
                                                            for primary_key in primary_keys])
                                                     for record in actual_records}
                self.assertSetEqual(expected_primary_key_values, actual_records_primary_key_values)

class TestHubspotAllFieldsStatic(TestHubspotAllFields):
    def name(self):
        return "tt_all_fields_static_data_test"

    def streams_under_test(self):
        """expected streams minus the streams not under test"""
        return {
            'owners',
            # 'subscription_changes', # BUG_TDL-14938 https://jira.talendforge.org/browse/TDL-14938
        }

    def get_properties(self):
        return {'start_date' : '2021-05-02T00:00:00Z'}
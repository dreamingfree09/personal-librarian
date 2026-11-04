"""F09/F10 regressions use only disposable synthetic catalogue state."""
from __future__ import annotations

from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
import json
import threading
import unittest
from unittest.mock import patch

from tests.test_date_evidence import DateServiceCase
from personal_librarian.catalogue.database import connect_existing_catalogue
from personal_librarian.catalogue.errors import DateEvidenceError
import personal_librarian.date_evidence as dates
from personal_librarian.date_evidence import (
    EvidenceInput, EvidenceType, parse_partial_date, record_evidence,
    resolve_preferred_date, set_owner_preferred_date,
)


class IntegrityCase(DateServiceCase):
    def assert_consistent(self):
        with closing(connect_existing_catalogue(self.database, read_only=True)) as c:
            self.assertEqual(c.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            self.assertEqual(c.execute('PRAGMA foreign_key_check').fetchall(), [])

    def snapshot(self):
        with closing(connect_existing_catalogue(self.database, read_only=True)) as c:
            return {table: [dict(r) for r in c.execute(f"SELECT * FROM {table} ORDER BY 1")]
                    for table in ("content_date_evidence", "content_preferred_dates",
                                  "preferred_date_basis", "organisation_events")}

    def evidence(self, c, value, kind=EvidenceType.EXIF_DATETIME_ORIGINAL, version="1"):
        run = self.run_id(c)
        return record_evidence(c, EvidenceInput(
            content_identity_id=self.content_ids[0], evidence_type=kind,
            raw_value=value, value=parse_partial_date(value), actor_type="system",
            actor_identifier="synthetic", provenance="synthetic-test",
            extractor_name="synthetic", extractor_version=version, analysis_run_id=run,
        )).date_evidence_id

    def run_id(self, c):
        run = c.execute("SELECT analysis_run_id FROM analysis_runs WHERE run_key='test'").fetchone()
        if run is None:
            run = (c.execute("INSERT INTO analysis_runs(run_key,analysis_kind) VALUES('test','date')").lastrowid,)
        return run[0]

    def resolve(self, c, version="preferred-date-policy-v1"):
        return resolve_preferred_date(c, content_identity_id=self.content_ids[0],
                                      analysis_run_id=self.run_id(c), policy_version=version)

    def action(self, key="A", value="2000", **overrides):
        args = dict(database_path=self.database, content_identity_id=self.content_ids[0],
                    action_id=key, value=value, actor="owner", reason="test",
                    provenance="owner-manual")
        args.update(overrides)
        return set_owner_preferred_date(**args)


class BasisIntegrityTests(IntegrityCase):
    def test_corroboration_reconciles_without_selection_event(self):
        with closing(connect_existing_catalogue(self.database, read_only=False)) as c:
            first = self.evidence(c, "2000-02")
            self.resolve(c)
            c.commit()
            before = self.snapshot()
            second = self.evidence(c, "2000-02", version="2")
            self.resolve(c)
            c.commit()
        after = self.snapshot()
        self.assertEqual(after['content_preferred_dates'], before['content_preferred_dates'])
        self.assertEqual(after['organisation_events'], before['organisation_events'])
        self.assertEqual({(r['date_evidence_id'], r['basis_role']) for r in after['preferred_date_basis']
                          if r['basis_state']=='current'}, {(first,'selected'),(second,'corroborating')})
        with closing(connect_existing_catalogue(self.database, read_only=False)) as c:
            result = self.resolve(c)
            self.assertFalse(result['changed'])
            self.assertFalse(result['basis_changed'])
            c.commit()
        self.assertEqual(self.snapshot(), after)
        self.assert_consistent()

    def test_conflict_role_changes_without_projection_or_event_change(self):
        with closing(connect_existing_catalogue(self.database, read_only=False)) as c:
            a = self.evidence(c, '2000')
            b = self.evidence(c, '2001', EvidenceType.GOOGLE_PHOTOS_TAKEOUT)
            self.resolve(c)
            c.commit()
            before = self.snapshot()
            d = self.evidence(c, '2000-02', EvidenceType.EMBEDDED_VIDEO_CAPTURE)
            # Correct a stale role in the mutable basis projection; raw evidence
            # and the preferred needs-review value remain unchanged.
            c.execute("UPDATE preferred_date_basis SET basis_role='corroborating' WHERE date_evidence_id=?", (a,))
            result = self.resolve(c)
            self.assertFalse(result['changed'])
            self.assertTrue(result['basis_changed'])
            c.commit()
        after = self.snapshot()
        self.assertEqual(after['content_preferred_dates'], before['content_preferred_dates'])
        self.assertEqual(after['organisation_events'], before['organisation_events'])
        self.assertEqual({(r['date_evidence_id'],r['basis_role']) for r in after['preferred_date_basis']},
                         {(a,'conflicting'),(b,'conflicting'),(d,'conflicting')})
        self.assert_consistent()

    def test_obsolete_basis_is_superseded_not_deleted(self):
        with closing(connect_existing_catalogue(self.database, read_only=False)) as c:
            weak = self.evidence(c, '2000', EvidenceType.FILESYSTEM_MODIFIED)
            self.resolve(c)
            c.commit()
            old_basis = self.snapshot()['preferred_date_basis'][0]
            self.evidence(c, '2001', EvidenceType.FILENAME_DERIVED)
            self.evidence(c, '2002', EvidenceType.FILENAME_DERIVED)
            self.resolve(c)
            c.commit()
            stable = self.snapshot()
            # A pre-existing stale current link is also reconciled when the
            # preferred needs-review signature does not change.
            c.execute("UPDATE preferred_date_basis SET basis_state='current', superseded_at=NULL "
                      "WHERE date_evidence_id=?", (weak,))
            self.assertTrue(self.resolve(c)['basis_changed'])
            c.commit()
            reconciled = self.snapshot()
            self.assertEqual(reconciled['content_preferred_dates'], stable['content_preferred_dates'])
            self.assertEqual(reconciled['organisation_events'], stable['organisation_events'])
            stable = reconciled
            self.resolve(c)
            c.commit()
        self.assertEqual(self.snapshot(), stable)
        obsolete = next(r for r in stable['preferred_date_basis'] if r['date_evidence_id']==weak)
        self.assertEqual(obsolete['preferred_date_basis_id'], old_basis['preferred_date_basis_id'])
        self.assertEqual(obsolete['linked_at'], old_basis['linked_at'])
        self.assertEqual(obsolete['basis_state'], 'superseded')
        self.assertIsNotNone(obsolete['superseded_at'])
        self.assertEqual(len(stable['content_date_evidence']), 3)
        self.assert_consistent()

    def test_unknown_gains_weak_basis_without_new_unknown_event(self):
        with closing(connect_existing_catalogue(self.database, read_only=False)) as c:
            self.resolve(c)
            c.commit()
            before = self.snapshot()
            weak = self.evidence(c, '2000', EvidenceType.FILESYSTEM_MODIFIED)
            result = self.resolve(c)
            c.commit()
        after = self.snapshot()
        self.assertFalse(result['changed'])
        self.assertTrue(result['basis_changed'])
        self.assertEqual(after['content_preferred_dates'], before['content_preferred_dates'])
        self.assertEqual(after['organisation_events'], before['organisation_events'])
        self.assertEqual(after['preferred_date_basis'][0]['date_evidence_id'], weak)
        self.assertEqual(after['preferred_date_basis'][0]['basis_role'], 'ignored_lower_authority')

    def test_policy_and_extractor_versions_and_partial_precision(self):
        with closing(connect_existing_catalogue(self.database, read_only=False)) as c:
            self.evidence(c, '2000')
            self.resolve(c)
            c.commit()
            before = self.snapshot()
            self.evidence(c, '2000', version='2')
            self.resolve(c)
            c.commit()
            self.assertEqual(self.snapshot()['organisation_events'], before['organisation_events'])
            self.resolve(c, 'test-policy-v2')
            c.commit()
            after = self.snapshot()
            self.resolve(c, 'test-policy-v2')
            c.commit()
        self.assertEqual(self.snapshot(), after)
        self.assertEqual(len(after['organisation_events']), len(before['organisation_events'])+1)
        p = after['content_preferred_dates'][0]
        self.assertEqual(p['selected_precision'], 'year')
        self.assertIsNone(p['selected_month'])
        self.assertIsNone(p['selected_day'])
        self.assertEqual(len(after['preferred_date_basis']),2)

    def test_owner_override_retains_authority_while_basis_reconciles(self):
        old = self.action('old', '1990')
        selected = self.action('new', '2000-02')
        before = self.snapshot()
        with closing(connect_existing_catalogue(self.database, read_only=False)) as c:
            agree = self.evidence(c, '2000-02-03')
            conflict = self.evidence(c, '2001', EvidenceType.GOOGLE_PHOTOS_TAKEOUT)
            weak = self.evidence(c, '2020', EvidenceType.FILESYSTEM_MODIFIED)
            result = self.resolve(c, 'test-policy-v2')
            self.assertTrue(result['owner_override_preserved'])
            self.assertFalse(result['changed'])
            c.commit()
            after = self.snapshot()
            self.resolve(c)
            c.commit()
        self.assertEqual(self.snapshot(), after)
        self.assertEqual(after['content_preferred_dates'], before['content_preferred_dates'])
        self.assertEqual(after['organisation_events'], before['organisation_events'])
        self.assertEqual({(r['date_evidence_id'],r['basis_role']) for r in after['preferred_date_basis']
                          if r['basis_state']=='current'},
                         {(selected['date_evidence_id'],'selected'),(agree,'corroborating'),
                          (conflict,'conflicting'),(weak,'ignored_lower_authority')})
        self.assertEqual(next(r['basis_state'] for r in after['preferred_date_basis']
                              if r['date_evidence_id']==old['date_evidence_id']), 'superseded')
        self.assert_consistent()


class OwnerActionIntegrityTests(IntegrityCase):
    def test_historical_retry_cannot_restore_old_authority(self):
        self.action()
        first = self.snapshot()
        self.assertFalse(self.action()['changed'])
        self.assertEqual(self.snapshot(), first)
        self.action("B", "2001-03")
        newer = self.snapshot()
        self.assertFalse(self.action()['changed'])
        self.assertEqual(self.snapshot(), newer)

    def test_action_id_conflict_is_rejected_without_any_write(self):
        self.action()
        before = self.snapshot()
        with self.assertRaises(DateEvidenceError):
            self.action(value="2002")
        self.assertEqual(self.snapshot(), before)

    def test_material_request_fields_are_bound_and_new_correction_remains_possible(self):
        self.action()
        self.action('B', '2001')
        before = self.snapshot()
        for changes in ({'actor':'someone-else'}, {'reason':'different'}, {'reason':None},
                        {'provenance':'different'}, {'value':'2000-01'}):
            with self.subTest(changes=changes), self.assertRaises(DateEvidenceError):
                self.action(**changes)
            self.assertEqual(self.snapshot(), before)
        self.action('C','2002-04')
        after = self.snapshot()
        self.assertEqual(after['organisation_events'][:2], before['organisation_events'])
        self.assertEqual(len(after['organisation_events']),3)
        self.assertEqual(after['content_preferred_dates'][0]['selected_year'],2002)
        self.assertEqual(after['content_preferred_dates'][0]['selected_month'],4)
        self.assert_consistent()

    def test_content_scoped_action_identity(self):
        self.action()
        self.action(content_identity_id=self.content_ids[1], value='2001')
        state = self.snapshot()
        self.assertEqual(len(state['organisation_events']),2)
        self.assertFalse(self.action()['changed'])
        self.assertEqual(self.snapshot(),state)

    def test_partial_dates_offsets_and_effectively_identical_spelling(self):
        for i, value in enumerate(('1987','1987-06','1987-06-14','1987-06-14T15:43:21.123456789+01:00')):
            self.action(str(i),value)
            before = self.snapshot()
            self.assertFalse(self.action(str(i),value)['changed'])
            self.assertEqual(self.snapshot(),before)
            self.assertEqual(dates._row_value(before['content_date_evidence'][-1]).render(),value)
        self.action('utc','2000-01-01T12:30Z')
        before = self.snapshot()
        self.assertFalse(self.action('utc','2000-01-01 12:30+00:00')['changed'])
        self.assertEqual(self.snapshot(),before)
        with self.assertRaises(DateEvidenceError):
            self.action('utc','2000-01-01T13:30+01:00')
        self.assertEqual(self.snapshot(),before)

    def legacy_action(self, key, value):
        append = dates._append_preferred_event
        def old_event(*args, **kwargs):
            kwargs.pop('details',None)
            append(*args,**kwargs)
        with patch.object(dates,'_append_preferred_event',side_effect=old_event):
            return self.action(key,value)

    def test_legacy_completed_actions_are_recognised_without_rewriting_history(self):
        self.legacy_action('A','1990')
        self.legacy_action('B','2000')
        before = self.snapshot()
        self.assertNotIn('owner_action_id',json.loads(before['organisation_events'][0]['details_json']))
        replay = self.action('A','1990')
        self.assertFalse(replay['changed'])
        self.assertFalse(replay['is_current'])
        self.assertEqual(self.snapshot(),before)
        for args in ({'value':'1991'},{'actor':'other'},{'reason':'other'},{'provenance':'other'}):
            with self.assertRaises(DateEvidenceError):
                self.action('A',**({'value':'1990'}|args))
            self.assertEqual(self.snapshot(),before)
        self.action('C','2020')
        self.assertEqual(self.snapshot()['organisation_events'][:2],before['organisation_events'])

    def test_ambiguous_legacy_action_fails_closed(self):
        self.legacy_action('A','1990')
        with patch.object(dates,'_owner_action_replay',return_value=None):
            self.legacy_action('A','2000')
        before=self.snapshot()
        with self.assertRaisesRegex(DateEvidenceError,'ambiguous'):
            self.action('A','1990')
        self.assertEqual(self.snapshot(),before)

    def test_uncompleted_legacy_evidence_is_not_adopted(self):
        with closing(connect_existing_catalogue(self.database,read_only=False)) as c:
            record_evidence(c,EvidenceInput(content_identity_id=self.content_ids[0],
                evidence_type=EvidenceType.OWNER_SET,raw_value='2000',value=parse_partial_date('2000'),
                actor_type='owner',actor_identifier='owner',provenance='owner-manual',owner_action_key='A'))
            c.commit()
        before=self.snapshot()
        with self.assertRaisesRegex(DateEvidenceError,'verifiable completed history'):
            self.action()
        self.assertEqual(self.snapshot(),before)

    def test_event_failure_rolls_back_evidence_projection_and_basis(self):
        self.action()
        before=self.snapshot()
        with patch.object(dates,'_append_preferred_event',side_effect=RuntimeError('injected')):
            with self.assertRaisesRegex(RuntimeError,'injected'):
                self.action('B','2001')
        self.assertEqual(self.snapshot(),before)
        self.assertTrue(self.action('B','2001')['changed'])
        self.assert_consistent()

    def test_invalid_owner_request_has_no_side_effects(self):
        self.action()
        before = self.snapshot()
        for changes in ({'actor':''},{'reason':''},{'provenance':''},{'action_id':''},
                        {'value':'2000-02-30'},{'content_identity_id':True}):
            with self.subTest(changes=changes), self.assertRaises(DateEvidenceError):
                self.action(**changes)
            self.assertEqual(self.snapshot(),before)

    def concurrent(self, *requests):
        barrier=threading.Barrier(len(requests))
        def invoke(args):
            barrier.wait(timeout=5)
            try:
                return self.action(**args)
            except DateEvidenceError as exc:
                return exc
        with ThreadPoolExecutor(max_workers=len(requests)) as pool:
            return list(pool.map(invoke,requests))

    def test_concurrent_identical_requests_create_one_action(self):
        results=self.concurrent({}, {})
        self.assertTrue(all(isinstance(r,dict) for r in results))
        self.assertEqual(sum(r['changed'] for r in results),1)
        state=self.snapshot()
        self.assertEqual([len(state[k]) for k in state],[1,1,1,1])
        self.assert_consistent()

    def test_concurrent_conflicting_requests_reject_one_without_partial_state(self):
        results=self.concurrent({'value':'2000'},{'value':'2001'})
        self.assertEqual(sum(isinstance(r,DateEvidenceError) for r in results),1)
        state=self.snapshot()
        self.assertEqual([len(state[k]) for k in state],[1,1,1,1])
        self.assertEqual(state['content_preferred_dates'][0]['selected_year'],
                         state['content_date_evidence'][0]['date_year'])
        self.assert_consistent()

    def test_concurrent_old_replay_and_new_correction_keep_new_authority(self):
        self.action()
        self.action('B','2001')
        history=self.snapshot()['organisation_events']
        results=self.concurrent({}, {'key':'C','value':'2002'})
        self.assertTrue(all(isinstance(r,dict) for r in results))
        state=self.snapshot()
        self.assertEqual(state['content_preferred_dates'][0]['selected_year'],2002)
        self.assertEqual(state['organisation_events'][:2],history)
        self.assertEqual(len(state['organisation_events']),3)
        self.assert_consistent()


if __name__ == '__main__':
    unittest.main()

"""Regression cases reproduced during the interrupted-work handoff review."""
import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from tools import atlas, _ids_disease, _ids_metabolite


class ReviewRegressions(unittest.TestCase):
    def test_ols_maintenance_payload_is_error_not_no_match(self):
        with patch.object(_ids_disease._common, 'get_json', return_value=({'error':'maintenance'}, 'stub')):
            with self.assertRaises(ValueError):
                _ids_disease.search_ols4('unknown')

    def test_pubchem_maintenance_payload_is_error_not_no_cid(self):
        with patch.object(_ids_metabolite, '_pubchem_json', return_value={'error':'maintenance'}):
            with self.assertRaises(ValueError):
                _ids_metabolite.lookup_pubchem('glycine')

    def test_locus_without_gene_does_not_mean_metabolite_absent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'atlas.csv'
            with path.open('w', newline='', encoding='utf-8') as handle:
                writer = csv.DictWriter(handle, fieldnames=['metabolite_name','gene_symbol','atlas','year','rsid'])
                writer.writeheader()
                writer.writerow(dict(metabolite_name='test compound',gene_symbol='N/A',atlas='Shin 2014',year='2014',rsid='rs1'))
            with patch.object(atlas, '_TABLE', None), patch.object(atlas, '_BY_NAME', {}), patch.object(atlas, '_BY_CHEBI', {}), patch.object(atlas, '_TABLE_PATH', None), patch.object(atlas, '_candidate_paths', return_value=[path]):
                result = atlas.get_effector_genes_atlas('', ['test compound'], {})
                self.assertEqual(result['status'], 'empty')
                text = ' '.join(result['caveats'])
                self.assertIn('none names a gene', text)
                self.assertNotIn('not present in the atlas', text)

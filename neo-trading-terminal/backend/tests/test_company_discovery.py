from app.terminal.catalogue import normalise
from app.terminal.server import create_app
from app.core.config import Settings
from fastapi.testclient import TestClient


def test_debt_certificate_is_not_classified_as_a_company_share():
    item={'id':'nse_cm|23964','symbol':'1050SCL31-ZP','name':'SEC RE NCD 10.5% SR IX',
          'exchange':'nse_cm','kind':'EQUITY'}
    assert normalise(item)['kind']=='OTHER'
    assert normalise({**item,'symbol':'BANK-EQ','name':'EXAMPLE BANK LTD'})['kind']=='EQUITY'


def test_company_name_sort_is_available_on_both_discovery_pages(tmp_path):
    app=create_app(Settings(_env_file=None,data_dir=tmp_path,environment='test',kotak_consumer_key=None))
    with TestClient(app) as client:
        for path in ('/api/stocks','/api/instruments'):
            response=client.get(path+'?sort=name&kind=EQUITY')
            assert response.status_code==200
            names=[i['name'] for i in response.json()['items']]
            assert names==sorted(names,key=str.casefold)

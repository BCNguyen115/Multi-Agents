import requests

with open('dataset/test_data/ecommerce_sales_analytics_5000.csv', 'rb') as f:
    files = {'file': ('ecommerce_sales_analytics_5000.csv', f, 'text/csv')}
    data = {
        'query': 'Dựng dashboard phân tích doanh thu và cơ cấu kinh doanh từ file bán hàng',
        'session_id': 'test_frontend_proxy_session'
    }
    print('Sending POST to http://localhost:3001/api/analyze...')
    res = requests.post('http://localhost:3001/api/analyze', files=files, data=data, timeout=120)
    print('Status:', res.status_code)
    try:
        j = res.json()
        print('JSON keys:', list(j.keys()))
        if 'dashboard_spec' in j and j['dashboard_spec']:
            charts = j['dashboard_spec'].get('charts', [])
            print('Number of charts:', len(charts))
            for i, c in enumerate(charts):
                title = c.get('title')
                dim = c.get('dimension')
                meas = c.get('measure')
                print(f'Chart {i+1}: {title} | dim={dim} | meas={meas}')
        else:
            print('No dashboard_spec in response:', j)
    except Exception as e:
        print('Error decoding JSON:', e, res.text[:300])

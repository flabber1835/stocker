"""Native-shaped isolated Alpaca observations; no network fallback exists."""
from tools.opening_gateway_qualification import LocalAlpaca, Response


class NativeWorkflowAlpaca(LocalAlpaca):
    def get(self,url,params):
        path = self.path(url)
        if path == '/v2/account/activities/FILL':
            self.requests['GET '+path] += 1
            order = self.orders[params['order_id']]
            assert order['status'] == 'filled'
            native_id = next(event['ref_id'] for event in self.events
                             if event['details']['order_id']==order['id'])
            return Response([{
                'id': native_id, 'activity_type':'FILL',
                'account_id':self.account_uuid, 'order_id':order['id'],
                'asset_id':order['asset_id'], 'symbol':order['symbol'],
                'side':order['side'], 'qty':order['filled_qty'],
                'price':order['filled_avg_price'],
                'transaction_time':order['filled_at'],
                'client_order_id':order['client_order_id'],
            }])
        result = super().get(url,params)
        if path == '/v2/account':
            result.payload['currency'] = 'USD'
        return result

    def post(self,url,body):
        result = super().post(url,body)
        result.payload['created_at'] = result.payload['submitted_at']
        result.payload['updated_at'] = result.payload['submitted_at']
        result.payload['filled_at'] = (result.payload['submitted_at']
            if result.payload['status']=='filled' else None)
        return result

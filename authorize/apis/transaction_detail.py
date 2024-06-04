from decimal import Decimal
from urllib.parse import urlencode

from suds import WebFault
from suds.client import Client

from authorize.exceptions import AuthorizeConnectionError, AuthorizeResponseError

PROD_URL = "https://api.authorize.net/soap/v1/Service.asmx?WSDL"
TEST_URL = "https://apitest.authorize.net/soap/v1/Service.asmx?WSDL"


class TransactionDetailAPI(object):
    def __init__(self, login_id, transaction_key, debug=True, test=False):
        self.url = TEST_URL if debug else PROD_URL
        self.login_id = login_id
        self.transaction_key = transaction_key
        self.transaction_options = urlencode(
            {
                "x_version": "3.1",
                "x_test_request": "Y" if test else "F",
                "x_delim_data": "TRUE",
                "x_delim_char": ";",
            }
        )

    @property
    def client(self):
        # Lazy instantiation of SOAP client, which hits the WSDL url
        if not hasattr(self, "_client"):
            self._client = Client(self.url)
        return self._client

    @property
    def client_auth(self):
        if not hasattr(self, "_client_auth"):
            self._client_auth = self.client.factory.create("MerchantAuthenticationType")
            self._client_auth.name = self.login_id
            self._client_auth.transactionKey = self.transaction_key
        return self._client_auth

    def _make_call(self, service, *args):
        # Provides standard API call error handling
        method = getattr(self.client.service, service)
        try:
            response = method(self.client_auth, *args)
        except WebFault as e:
            raise AuthorizeConnectionError("Error contacting SOAP API.")
        if response.resultCode != "Ok":
            error = response.messages[0][0]
            e = AuthorizeResponseError("%s: %s" % (error.code, error.text))
            e.full_response = {
                "response_code": error.code,
                "response_text": error.text,
            }
            raise e
        return response

    def details(self, transaction_id):
        response = self._make_call("GetTransactionDetails", transaction_id)
        return response

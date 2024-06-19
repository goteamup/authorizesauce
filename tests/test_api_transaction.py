from datetime import date
from unittest import TestCase

import requests
import responses

from authorize.apis.transaction import PROD_URL, TEST_URL, TransactionAPI
from authorize.data import Address, CreditCard
from authorize.exceptions import AuthorizeConnectionError, AuthorizeResponseError

SUCCESS = (
    "1;1;1;This transaction has been approved.;IKRAGJ;Y;2171062816;;;20.00;CC"
    ";auth_only;;Jeffrey;Schenck;;45 Rose Ave;Venice;CA;90291;USA;;;;;;;;;;;;"
    ";;;;;375DD9293D7605E20DF0B437EE2A7B92;P;2;;;;;;;;;;;XXXX1111;Visa;;;;;;;"
    ";;;;;;;;;;Y"
)
PARSED_SUCCESS = {
    "cvv_response": "P",
    "authorization_code": "IKRAGJ",
    "response_code": "1",
    "amount": "20.00",
    "transaction_type": "auth_only",
    "avs_response": "Y",
    "response_reason_code": "1",
    "response_reason_text": "This transaction has been approved.",
    "transaction_id": "2171062816",
}
ERROR = (
    "2;1;2;This transaction has been declined.;000000;N;2171062816;;;20.00;CC"
    ";auth_only;;Jeffrey;Schenck;;45 Rose Ave;Venice;CA;90291;USA;;;;;;;;;;;;"
    ";;;;;375DD9293D7605E20DF0B437EE2A7B92;N;1;;;;;;;;;;;XXXX1111;Visa;;;;;;;"
    ";;;;;;;;;;Y"
)
PARSED_ERROR = {
    "cvv_response": "N",
    "authorization_code": "000000",
    "response_code": "2",
    "amount": "20.00",
    "transaction_type": "auth_only",
    "avs_response": "N",
    "response_reason_code": "2",
    "response_reason_text": "This transaction has been declined.",
    "transaction_id": "2171062816",
}


class TransactionAPITests(TestCase):
    def setUp(self):
        self.api = TransactionAPI("123", "456")
        self.year = date.today().year + 10
        self.credit_card = CreditCard("4111111111111111", self.year, 1, "911")
        self.address = Address("45 Rose Ave", "Venice", "CA", "90291")

    def test_basic_api(self):
        api = TransactionAPI("123", "456")
        self.assertEqual(api.url, TEST_URL)
        api = TransactionAPI("123", "456", debug=False)
        self.assertEqual(api.url, PROD_URL)

    @responses.activate
    def test_make_call(self):
        response = responses.post(TEST_URL, body=SUCCESS)
        result = self.api._make_call({"a": "1", "b": "2"})
        self.assertEqual(response.calls[0].request.body, "a=1&b=2")
        self.assertEqual(result, PARSED_SUCCESS)

    @responses.activate
    def test_make_call_connection_error(self):
        # Mock the response to produce an IOError.
        responses.add(responses.POST, TEST_URL, body=requests.Timeout())
        with self.assertRaises(AuthorizeConnectionError):
            self.api._make_call({"a": "1", "b": "2"})

    @responses.activate
    def test_make_call_http_error(self):
        # Mock the response to produce an IOError.
        responses.post(TEST_URL, status=500, body="Internal Server Error")
        with self.assertRaises(AuthorizeResponseError) as e:
            self.api._make_call({"a": "1", "b": "2"})
            self.assertEqual(e.msg, f"Received HTTP status code 500 when calling {TEST_URL}")

    @responses.activate
    def test_make_call_response_error(self):
        responses.add(responses.POST, TEST_URL, body=ERROR)
        try:
            self.api._make_call({"a": "1", "b": "2"})
        except AuthorizeResponseError as e:
            self.assertTrue(str(e).startswith("This transaction has been declined."))
            self.assertEqual(e.full_response, PARSED_ERROR)

    def test_add_params(self):
        self.assertEqual(self.api._add_params({}), {})
        params = self.api._add_params({}, credit_card=self.credit_card)
        self.assertEqual(
            params,
            {
                "x_card_num": "4111111111111111",
                "x_exp_date": "01-{0}".format(self.year),
                "x_card_code": "911",
            },
        )
        params = self.api._add_params({}, address=self.address)
        self.assertEqual(
            params,
            {
                "x_address": "45 Rose Ave",
                "x_city": "Venice",
                "x_state": "CA",
                "x_zip": "90291",
                "x_country": "US",
            },
        )
        params = self.api._add_params(
            {}, credit_card=self.credit_card, address=self.address
        )
        self.assertEqual(
            params,
            {
                "x_card_num": "4111111111111111",
                "x_exp_date": f"01-{self.year}",
                "x_card_code": "911",
                "x_address": "45 Rose Ave",
                "x_city": "Venice",
                "x_state": "CA",
                "x_zip": "90291",
                "x_country": "US",
            },
        )

    @responses.activate
    def test_auth(self):
        response = responses.post(TEST_URL, body=SUCCESS)
        result = self.api.auth(20, self.credit_card, self.address)
        self.assertEqual(
            response.calls[0].request.body.split("&").sort(),
            "https://test.authorize.net/gateway/transact.dll?x_login=123"
            "&x_zip=90291&x_card_num=4111111111111111&x_amount=20.00"
            "&x_tran_key=456&x_city=Venice&x_country=US&x_version=3.1"
            "&x_state=CA&x_delim_char=%3B&x_address=45+Rose+Ave"
            f"&x_exp_date=01-{self.year}&x_test_request=FALSE&x_card_code=911"
            "&x_type=AUTH_ONLY&x_delim_data=TRUE".split("&").sort(),
        )
        self.assertEqual(result, PARSED_SUCCESS)

    @responses.activate
    def test_capture(self):
        response = responses.post(TEST_URL, body=SUCCESS)
        result = self.api.capture(20, self.credit_card, self.address)
        self.assertEqual(
            response.calls[-1].request.body.split("&").sort(),
            "https://test.authorize.net/gateway/transact.dll?x_login=123"
            "&x_zip=90291&x_card_num=4111111111111111&x_amount=20.00"
            "&x_tran_key=456&x_city=Venice&x_country=US&x_version=3.1"
            "&x_state=CA&x_delim_char=%3B&x_address=45+Rose+Ave"
            f"&x_exp_date=01-{self.year}&x_test_request=FALSE&x_card_code=911"
            "&x_type=AUTH_CAPTURE&x_delim_data=TRUE".split("&").sort(),
        )
        self.assertEqual(result, PARSED_SUCCESS)

    @responses.activate
    def test_settle(self):
        response = responses.post(TEST_URL, body=SUCCESS)

        # Test without specified amount
        result = self.api.settle("123456")
        self.assertEqual(
            response.calls[-1].request.body.split("&").sort(),
            f"{TEST_URL}?x_login=123"
            "&x_trans_id=123456&x_version=3.1&x_delim_char=%3B"
            "&x_type=PRIOR_AUTH_CAPTURE&x_delim_data=TRUE&x_tran_key=456"
            "&x_test_request=FALSE".split("&").sort(),
        )
        self.assertEqual(result, PARSED_SUCCESS)

        # Test with specified amount
        result = self.api.settle("123456", amount=10)
        self.assertEqual(
            response.calls[-1].request.body.split("&").sort(),
            f"{TEST_URL}?x_login=123"
            "&x_trans_id=123456&x_version=3.1&x_delim_char=%3B"
            "&x_type=PRIOR_AUTH_CAPTURE&x_amount=10.00&x_delim_data=TRUE"
            "&x_tran_key=456&x_test_request=FALSE".split("&").sort(),
        )
        self.assertEqual(result, PARSED_SUCCESS)

    @responses.activate
    def test_credit(self):
        response = responses.post(TEST_URL, body=SUCCESS)

        # Test with transaction_id, amount
        result = self.api.credit("1111", "123456", 10)
        self.assertEqual(
            response.calls[-1].request.body.split("&").sort(),
            f"{TEST_URL}?x_login=123"
            "&x_trans_id=123456&x_version=3.1&x_amount=10.00&x_delim_char=%3B"
            "&x_type=CREDIT&x_card_num=1111&x_delim_data=TRUE&x_tran_key=456"
            "&x_test_request=FALSE".split("&").sort(),
        )
        self.assertEqual(result, PARSED_SUCCESS)

    @responses.activate
    def test_void(self):
        response = responses.post(TEST_URL, body=SUCCESS)
        result = self.api.void("123456")
        print(response.calls[-1].request.body)
        self.assertEqual(
            response.calls[-1].request.body.split("&").sort(),
            "x_login=123"
            "&x_trans_id=123456&x_version=3.1&x_delim_char=%3B&x_type=VOID"
            "&x_delim_data=TRUE&x_tran_key=456&x_test_request=FALSE".split("&").sort(),
        )
        self.assertEqual(result, PARSED_SUCCESS)

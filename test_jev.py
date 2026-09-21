"""验证官方请求结构、概率分布和 Score 量程；无需真实 Key。"""
import copy
import io
import json
import unittest
from unittest.mock import patch

import jev


class JevTests(unittest.TestCase):
    def call(self, kind, criteria, answer):
        body = json.dumps({'answers': {'judgment': answer}}).encode()
        with patch.object(jev.urllib.request.OpenerDirector, 'open', return_value=io.BytesIO(body)) as call:
            result = jev.evaluate('原始文本', '判断问题', 'fake-key', kind, criteria)
        request = call.call_args.args[0]
        payload = json.loads(request.data)
        self.assertEqual(payload['model'], 'jev-latest')
        self.assertEqual(payload['state'], '原始文本')
        self.assertEqual(payload['questions']['judgment']['type'], kind)
        self.assertEqual(payload['questions']['judgment']['instructions'], '判断问题')
        self.assertNotIn('fake-key', request.data.decode())
        if kind != 'noul':
            self.assertEqual(payload['questions']['judgment']['criteria'], criteria)
        return result

    def test_all_three_request_and_response_shapes(self):
        self.assertEqual(self.call('noul', None, {'type': 'noul', 'noul': 0.6}), {'type': 'noul', 'noul': 0.6})
        choice = {'type': 'choice', 'choice': '退款', 'probabilities': {'退款': 0.9, '其他': 0.1}, 'confidence': 0.7}
        self.assertEqual(self.call('choice', {'退款': '要求退钱', '其他': None}, choice), choice)
        score = {'type': 'score', 'score': 1.4, 'probabilities': {'0': 0.1, '1': 0.4, '2': 0.5},
                 'confidence': 0.3, 'legend': {'0': '轻微', '1': '中等', '2': '严重'}}
        self.assertEqual(self.call('score', ['轻微', '中等', '严重'], score), score)

    def test_rejects_invalid_distribution_and_score(self):
        question = jev.build_question('问题', 'score', ['低', '高'])
        valid = {'type': 'score', 'score': 0.8, 'probabilities': {'0': 0.2, '1': 0.8},
                 'confidence': 0.5, 'legend': {'0': '低', '1': '高'}}
        patches = [
            {'type': 'choice'}, {'score': -0.1}, {'score': 1.1}, {'score': float('nan')},
            {'score': True}, {'confidence': 2}, {'confidence': '0.5'},
            {'probabilities': {'0': 0.2}}, {'probabilities': {'0': 0.9, '1': 0.9}},
            {'probabilities': {'0': float('nan'), '1': 0.8}},
            {'probabilities': {'0': True, '1': 0}}, {'legend': None},
        ]
        for change in patches:
            with self.subTest(change=change), self.assertRaises(jev.AnswerError):
                answer = copy.deepcopy(valid)
                answer.update(change)
                jev.read_answer({'answers': {'judgment': answer}}, question)
        for response in [None, [], {}, {'answers': {}}, {'answers': {'judgment': []}}]:
            with self.subTest(response=response), self.assertRaises(jev.AnswerError):
                jev.read_answer(response, question)

    def test_choice_unknown_option_rejected(self):
        question = jev.build_question('问题', 'choice', {'a': None, 'b': None})
        with self.assertRaises(jev.AnswerError):
            jev.read_answer({'answers': {'judgment': {'type': 'choice', 'choice': 'c',
                'probabilities': {'a': 0.8, 'b': 0.2}, 'confidence': 0.5}}}, question)

    def test_legacy_ask_returns_probability(self):
        with patch.object(jev, 'evaluate', return_value={'type': 'noul', 'noul': 0.75}) as evaluate:
            self.assertEqual(jev.ask('文本', '问题', 'fake-key'), 0.75)
            evaluate.assert_called_once_with('文本', '问题', 'fake-key')


if __name__ == '__main__':
    unittest.main()

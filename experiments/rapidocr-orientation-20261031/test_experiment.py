import unittest
from experiment import evaluate, unrotate


class OrientationTests(unittest.TestCase):
    def test_clockwise_rotation_inverse_at_asymmetric_points(self):
        self.assertEqual(unrotate((.2,.3),0),(.2,.3))
        self.assertEqual(unrotate((.7,.2),90),(.2,.30000000000000004))
        self.assertEqual(unrotate((.8,.7),180),(.19999999999999996,.30000000000000004))
        with self.assertRaises(ValueError):unrotate((.2,.3),45)

    def test_exact_number_does_not_pass_after_decimal_or_sign_loss(self):
        check={'id':'cell','rect':[0,0,1,1],'expected':'-7.3%','kind':'exact'}
        for text,expected in [('-7.3%',1),('7.3%',0),('-73%',0),('-7.3',0)]:
            raw={'lines':[text],'boxes_normalized_original':[[[.1,.1],[.8,.1],[.8,.2],[.1,.2]]]}
            self.assertEqual(evaluate(raw,[check])['matched'],expected)

    def test_same_value_elsewhere_does_not_hide_missing_cell(self):
        raw={'lines':['7.3%'],'boxes_normalized_original':[[[.6,.1],[.8,.1],[.8,.2],[.6,.2]]]}
        check={'id':'left','rect':[0,0,.5,1],'expected':'7.3%','kind':'exact'}
        self.assertEqual(evaluate(raw,[check])['matched'],0)


if __name__=='__main__':unittest.main()

import unittest
from page_orientation import axis_evidence, choose_direction, inverse_point, language_support


class PageDirectionTests(unittest.TestCase):
    def test_pure_numbers_cannot_vote_even_at_high_confidence(self):
        raw={'lines':['990.0','17.5%','1234567890123456'],'scores':[1,1,1],
             'boxes_normalized':[[[.1,y],[.8,y],[.8,y+.02],[.1,y+.02]] for y in [.1,.4,.7]],'render_pixels':[1000,1000]}
        self.assertFalse(language_support(raw)['enough'])
        self.assertEqual(language_support(raw)['mass'],0)

    def test_conflicting_directions_are_not_resolved_by_tie_break(self):
        cs=[{'correction_clockwise':a,'support':{'mass':m,'enough':True}} for a,m in [(0,100),(180,90)]]
        self.assertIsNone(choose_direction(cs)['correction_clockwise'])
        cs[1]['support']['mass']=50
        self.assertEqual(choose_direction(cs)['correction_clockwise'],0)

    def test_single_heading_or_single_band_does_not_establish_page_direction(self):
        raw={'lines':['This is a sufficiently long heading']*3,'scores':[.99]*3,
             'boxes_normalized':[[[.1,.1],[.8,.1],[.8,.12],[.1,.12]]]*3,'render_pixels':[1000,1000]}
        self.assertFalse(language_support(raw)['enough'])

    def test_mixed_axis_and_blank_are_unknown(self):
        h=[[0,0],[100,0],[100,10],[0,10]];v=[[0,0],[10,0],[10,100],[0,100]]
        self.assertIsNone(axis_evidence([])['axis_clockwise'])
        self.assertIsNone(axis_evidence([h,h,h,v,v,v])['axis_clockwise'])
        self.assertEqual(axis_evidence([v,v,v])['axis_clockwise'],90)

    def test_quarter_turn_box_mapping(self):
        x,y=inverse_point((.3,.8),270)
        self.assertAlmostEqual(x,.2);self.assertAlmostEqual(y,.3)


if __name__=='__main__':unittest.main()

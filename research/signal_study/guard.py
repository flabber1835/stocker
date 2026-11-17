"""Prohibit Core transitions while reading retained research evidence."""
import sys


class CoreGuard:
    def __enter__(self):
        from sentinel.core.kernel import advance_session
        self.code=advance_session.__code__; self.calls=0; self.previous=sys.getprofile()
        sys.setprofile(self.watch)
        return self

    def watch(self,frame,event,arg):
        if event=='call' and frame.f_code is self.code:
            self.calls+=1
            raise RuntimeError('Signal research cannot advance Wealth Core')

    def __exit__(self,*args):
        sys.setprofile(self.previous)

    def receipt(self):
        return dict(canonical_core_transition_calls=self.calls,status='PASS' if self.calls==0 else 'FAIL')

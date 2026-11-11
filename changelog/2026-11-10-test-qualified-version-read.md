# TEST qualified-version read authority

- Effective-policy simulation confirmed that the retained TEST deployment supplement allowed `lambda:GetFunction` on version 4 only, while the reviewed activation had published version 5.
- The bounded revision retains version 4 and adds only the actual `live` version 5, after verifying its code against the validated artifact. The owning CloudFormation template does not manage this existing supplement.
- Candidate simulation permits versions 4 and 5 and denies the next version and an unrelated function. Every other statement, policy, attached policy and role trust remains sealed and checked.
- Remove the unrelated hidden-environment normalization and retain a precise, safe qualified-version-read rejection phase.

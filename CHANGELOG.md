# Changelog

## [0.4.0](https://github.com/EuroUnionConsult/resoiltwin/compare/v0.3.0...v0.4.0) (2026-09-03)


### ⚠ BREAKING CHANGES

* require the shared key on every route but /health

### Features

* add a server layer that holds the api key ([ce4b97b](https://github.com/EuroUnionConsult/resoiltwin/commit/ce4b97b8fe0533c643ceae80f8410a4e2fdc8f31))
* add the data console ([2028021](https://github.com/EuroUnionConsult/resoiltwin/commit/2028021e6dc5fcf4c07317b86d6dbc2a7f815e59))
* put a password at the console door ([9dce165](https://github.com/EuroUnionConsult/resoiltwin/commit/9dce165356592973062e1b73a3bfbac17d434fa6))
* require the shared key on every route but /health ([ba0b2f1](https://github.com/EuroUnionConsult/resoiltwin/commit/ba0b2f1f63e86dbb9fc3ca6bf763731ad476effb))
* serve the console in English by default, with Portuguese on request ([7e86b50](https://github.com/EuroUnionConsult/resoiltwin/commit/7e86b50eb6a6dfe2d61b3f729ffa7e42470ae1a7))
* teach the restore script to load a remote installation ([786a91e](https://github.com/EuroUnionConsult/resoiltwin/commit/786a91e2d7485669390519a01b5dda2c1a9190bf))


### Bug Fixes

* give the geometry vocabulary a word for traced and for constructed areas ([b8659d3](https://github.com/EuroUnionConsult/resoiltwin/commit/b8659d3f39d7b25c3b3ae08db871526428f41d46))
* read the deployer and database identifiers from the environment ([e75a84d](https://github.com/EuroUnionConsult/resoiltwin/commit/e75a84d8f3b2331f78c655668b093e1f3110bbc3))
* report the installed version, and stop claiming nothing was deployed ([8083bc1](https://github.com/EuroUnionConsult/resoiltwin/commit/8083bc17d08abe3a2c5f5f92029771afdbab22e8))
* stop the coordinate guard from biting a timestamp ([bf3fd90](https://github.com/EuroUnionConsult/resoiltwin/commit/bf3fd90667938a20d9592896124d7b5a8fccea42))


### Documentation

* bring the README up to the state the repository is actually in ([fd02eae](https://github.com/EuroUnionConsult/resoiltwin/commit/fd02eaed1e1b5b47930cd48e992cd2d7d01d0ca7))
* give the cell both its sides, and let Porto contradict the sentence ([132178f](https://github.com/EuroUnionConsult/resoiltwin/commit/132178f0ba1e907bb180bf44c217bd91553b005f))
* put the five evidence notes into English, in place ([5ef8138](https://github.com/EuroUnionConsult/resoiltwin/commit/5ef813884b9e7911377d2d77e683c7c4940bdd00))
* record the five Azure decisions taken on 31/08/2026 ([2b58811](https://github.com/EuroUnionConsult/resoiltwin/commit/2b5881183fb8362f6653db5263b12151b26711b2))
* say that the repository never kept the rule the notes claimed ([52de375](https://github.com/EuroUnionConsult/resoiltwin/commit/52de375e6cc3d1751e581df2455d523202d26c91))

## [0.3.0](https://github.com/EuroUnionConsult/resoiltwin/compare/v0.2.0...v0.3.0) (2026-08-31)


### Features

* add a single-reservoir daily water balance ([986a521](https://github.com/EuroUnionConsult/resoiltwin/commit/986a52187bfdb1a9c9172160104e3ce5fd6c802c))
* add the azure infrastructure as bicep templates and a deployment guide ([62ba3eb](https://github.com/EuroUnionConsult/resoiltwin/commit/62ba3ebc55a53a4bc05772cf72ea8e55d4d9085a))
* add the water balance route ([ad1bc7d](https://github.com/EuroUnionConsult/resoiltwin/commit/ad1bc7df54a94049fd027807371deffc228fb440))
* add water balance ingestion ([e8c52ea](https://github.com/EuroUnionConsult/resoiltwin/commit/e8c52eaa7599595268591e3644fa3ec7b8c7b257))
* ask the reanalysis for the reference evapotranspiration by default ([4ffd763](https://github.com/EuroUnionConsult/resoiltwin/commit/4ffd763fe9bd80077055ddf1efef0addb226dfa4))
* give the ingestion job somewhere to record the window it asked for ([7ab7e6c](https://github.com/EuroUnionConsult/resoiltwin/commit/7ab7e6c4ec94f15e95c4155e80017709cbea2548))
* **infra:** carry the write key from the vault into the container ([51dd472](https://github.com/EuroUnionConsult/resoiltwin/commit/51dd47201af781d2cf12a6f7c289d294937b5dd3))
* let a human see which ingestion runs need attention ([19652f0](https://github.com/EuroUnionConsult/resoiltwin/commit/19652f05048ce1aa44de5b29fd60bb987fb5b7bd))
* make the ingestions record both windows, the one asked for and the one covered ([a680077](https://github.com/EuroUnionConsult/resoiltwin/commit/a680077e7dee8ca2d45b572ee84388ae693c7b24))
* put both windows on every job row and let the reader set the threshold ([19fb22a](https://github.com/EuroUnionConsult/resoiltwin/commit/19fb22a140ccf1c9f84a92fce1b1e52def26dd08))
* read the reference evapotranspiration the reanalysis already carries ([b76775e](https://github.com/EuroUnionConsult/resoiltwin/commit/b76775e1d60fc5dbd42f673d8cf25622a129d774))
* record on every weather row what its number summarises ([86ed3d0](https://github.com/EuroUnionConsult/resoiltwin/commit/86ed3d0e1d15332273b9a1e642b7f0601b908d8b))
* record which origin file each reanalysis day was read from ([e719ab8](https://github.com/EuroUnionConsult/resoiltwin/commit/e719ab877f4d80bdcc9a6b8438ad3d3ffab57566))
* require a shared key on every route that writes ([3c31452](https://github.com/EuroUnionConsult/resoiltwin/commit/3c31452d656a04d6e6a726bb89818c5e824d01b6))


### Bug Fixes

* declare a job window that is true for every variable, not just for some ([565a653](https://github.com/EuroUnionConsult/resoiltwin/commit/565a653b65d9007dd621f3d656ceabb040dd2a7f))
* declare httpx as a runtime dependency ([9852021](https://github.com/EuroUnionConsult/resoiltwin/commit/98520217bb5ab7eeaec49d41b7b3da9dd143eeeb))
* drop the name the create accepted, and classify by sqlstate ([339e22f](https://github.com/EuroUnionConsult/resoiltwin/commit/339e22f1cf1a308f628be24527a370c694ff3e75))
* drop the one absurd reading, not the whole run that carried it ([cd2f4ef](https://github.com/EuroUnionConsult/resoiltwin/commit/cd2f4ef6d63e71d34fb2a7b8fc209beddf22b947))
* make the EO job declare the window it covered, and refuse days it did not ask for ([2b63aef](https://github.com/EuroUnionConsult/resoiltwin/commit/2b63aef1af1cd11bf14ace2878f92c31c5ce71cf))
* make the mutation harness guards fire in the shapes the platform produces ([a7ed192](https://github.com/EuroUnionConsult/resoiltwin/commit/a7ed19269a473d325cf2d88a8dd6a45f2673844a))
* read the weather variable the caller asked for, not the first one found ([4f17fe5](https://github.com/EuroUnionConsult/resoiltwin/commit/4f17fe5ce8223dde7d9d31ee8b54db836874e61a))
* refuse a cell with no data instead of writing NaN as an exact reading ([a69d3f1](https://github.com/EuroUnionConsult/resoiltwin/commit/a69d3f1777c8a8f0f2ecc5e824981085777e302c))
* stop satellite rows from claiming a quality nobody checked ([0d62c62](https://github.com/EuroUnionConsult/resoiltwin/commit/0d62c6272686b5e42392bcb97dc88226e24cdd04))


### Documentation

* record decision 7 and how the write key reaches production ([39c80e2](https://github.com/EuroUnionConsult/resoiltwin/commit/39c80e21eb3b73a5e3973c1209cdc23d10163774))
* record the first water balance run ([8e9e651](https://github.com/EuroUnionConsult/resoiltwin/commit/8e9e6519d27abb6e45a2b54727095463671c053d))
* say that nothing but zero came out of the first water balance ([7ada1f5](https://github.com/EuroUnionConsult/resoiltwin/commit/7ada1f5937cc5dbbe8387b4817fc1068e9e95f6d))

## [0.2.0](https://github.com/EuroUnionConsult/resoiltwin/compare/v0.1.0...v0.2.0) (2026-08-30)


### Features

* add a one-command restore for the development dataset ([f43d2e9](https://github.com/EuroUnionConsult/resoiltwin/commit/f43d2e9aa86b127ed706422e4b127d4b9c0982f4))
* add cdse client with token reuse and scene discovery ([6fb0e6f](https://github.com/EuroUnionConsult/resoiltwin/commit/6fb0e6f4acb03df9bb11ff8788301cac2c97bdb6))
* add climate data store client with async job handling ([ddda9b1](https://github.com/EuroUnionConsult/resoiltwin/commit/ddda9b11fe6b14c2d559bdae0fc8ffb07754f738))
* add eo sync and job status routes ([1911a80](https://github.com/EuroUnionConsult/resoiltwin/commit/1911a80aae5ee1ede383a36084d1de49d310d3dc))
* add idempotent eo ingestion service ([8e347c0](https://github.com/EuroUnionConsult/resoiltwin/commit/8e347c080f76b3c363b11080e513ddea085a06c4))
* add ingestion job model with status domain ([dd06814](https://github.com/EuroUnionConsult/resoiltwin/commit/dd0681459d04602fd7afb5b1a4dd13a93c062bd0))
* add ipma station ingestion for observed weather ([70f673b](https://github.com/EuroUnionConsult/resoiltwin/commit/70f673b493a5bc1f89f1f3cdb8f887396c7d8195))
* add reanalysis ingestion for weather series ([1b8e80a](https://github.com/EuroUnionConsult/resoiltwin/commit/1b8e80adcfd6eaad0fbcc753e3f1a570b7af7e4f))
* add scl-masked evalscript as a second versioned script ([d2bafe9](https://github.com/EuroUnionConsult/resoiltwin/commit/d2bafe97125825bb9ed32b3685581a006dc728fb))
* add versioned evalscript and polygon statistics with utm guard ([4e3314a](https://github.com/EuroUnionConsult/resoiltwin/commit/4e3314a0ec31438e85c4041874852473486d74ed))
* add weather metric vocabulary with distance-aware provenance ([9a8de6b](https://github.com/EuroUnionConsult/resoiltwin/commit/9a8de6b9a6d8e40986e376598b90395dfd7f0741))
* add weather sync routes ([4860757](https://github.com/EuroUnionConsult/resoiltwin/commit/4860757592637f53da02b5ccc13d4abe4cb7491d))
* let the sync choose between masked and unmasked scripts ([6fcc87d](https://github.com/EuroUnionConsult/resoiltwin/commit/6fcc87de280bd4f52150b9121748b10635cf2cc3))
* record the processing version on the ingestion job ([383da6e](https://github.com/EuroUnionConsult/resoiltwin/commit/383da6e235c8fcf35cd441ffd8a136852b99a3d6))
* soil digital twin backend with provenance-preserving observation model ([e9ccc7e](https://github.com/EuroUnionConsult/resoiltwin/commit/e9ccc7ed9a5ce089dd6048b2bc57f137b77c281f))


### Bug Fixes

* align the ingestion job processing version with the observation column ([7eeb6d5](https://github.com/EuroUnionConsult/resoiltwin/commit/7eeb6d5e46919d477f924cec8b2526789cca48f1))
* compute station distance instead of trusting a passed-in value ([f440727](https://github.com/EuroUnionConsult/resoiltwin/commit/f440727aca582b89ae1ec71736c517498efdf4d0))
* degrade gracefully when CDSE error bodies are not valid json ([909087d](https://github.com/EuroUnionConsult/resoiltwin/commit/909087d1f9b5d198e1a886c366cb4475e1beaeba))
* fail the ipma job when the station changed under the same identity ([fa7f292](https://github.com/EuroUnionConsult/resoiltwin/commit/fa7f292b83991381efa5d27425c44adb0a730b63))
* harden CDS response parsing and tighten the grid coverage guard ([0168488](https://github.com/EuroUnionConsult/resoiltwin/commit/0168488b81e9e97198123d5dd6fe51c17a786d14))
* let the caller set the station radius and stop naming a window the ipma path has not ([d7364b6](https://github.com/EuroUnionConsult/resoiltwin/commit/d7364b68ae2c418e918c50f248612d379221134b))
* make the reanalysis job declare the window it covered ([68d09d7](https://github.com/EuroUnionConsult/resoiltwin/commit/68d09d7daaa89471e5c5715d52ae0204f6cc304a))
* make the reanalysis version and the client row contract testable ([b03d73a](https://github.com/EuroUnionConsult/resoiltwin/commit/b03d73a4c5bec2a6f170773838b28b822ec05e9c))
* measure the station feed delay against its publication, not our clock ([723513b](https://github.com/EuroUnionConsult/resoiltwin/commit/723513b6251575e1e3119b01b91f13705f968c6b))
* only fail the ipma job when the run wrote nothing at all ([f93c2a6](https://github.com/EuroUnionConsult/resoiltwin/commit/f93c2a6a0b8a28b5b37b18ac274be2ce8026cbb7))
* paginate catalog search, declare cql2-json filter-lang, and surface catalog error bodies ([8943aad](https://github.com/EuroUnionConsult/resoiltwin/commit/8943aadf9863769f400093eb0f27fe6d5eb4c3c7))
* pin the publication margin and stop trusting the header blindly ([d22a3f7](https://github.com/EuroUnionConsult/resoiltwin/commit/d22a3f7d9b1fe58bde1045ab1271a2aeb841fa3c))
* read every day in the reanalysis zip, not just the first ([96717e8](https://github.com/EuroUnionConsult/resoiltwin/commit/96717e8066ba87303409f693b9e74d611b73e2b5))
* read the site's grid cell instead of averaging the requested box ([7dbcb0d](https://github.com/EuroUnionConsult/resoiltwin/commit/7dbcb0d5e43e8fa02e5cf9cb6e848b2e900ef6c6))
* reject weather station values the sun says were never measured ([df13177](https://github.com/EuroUnionConsult/resoiltwin/commit/df131770bf8f9004057eca3b95e2a4abe58b9592))
* remove the silent default for DATABASE_URL ([24afe4e](https://github.com/EuroUnionConsult/resoiltwin/commit/24afe4eeb1028470a7ff91867572b0a2316d7e12))
* require explicit evalscript for hashing, support MultiPolygon AOIs, and stop partial outputs from aborting a series ([5698a74](https://github.com/EuroUnionConsult/resoiltwin/commit/5698a7429c2051b1ef42226a515a342527f7fd6d))


### Documentation

* document the two evalscript versions and their provenance ([6dc4692](https://github.com/EuroUnionConsult/resoiltwin/commit/6dc46926b2b4c9a77c4d6a8b2e9652e08c18f66e))
* flag the cloud-contaminated dates in the phase B note ([00dc33f](https://github.com/EuroUnionConsult/resoiltwin/commit/00dc33f669fa91f59a9cc3dd0a2028383a1c424b))
* keep the parcel geometry out of the public evidence note ([1901506](https://github.com/EuroUnionConsult/resoiltwin/commit/1901506f31e7fc424612dea90ed75cd2aa50e474))
* pin the claims that a reader can check against the data ([019488f](https://github.com/EuroUnionConsult/resoiltwin/commit/019488fd8cabd03e6a94102ce638cd5bcfaf1f51))
* record the first automated copernicus ingestion ([813fad2](https://github.com/EuroUnionConsult/resoiltwin/commit/813fad2228d8747bfb9aacaef1ce2c53a277110f))
* record the first weather ingestion ([2448f65](https://github.com/EuroUnionConsult/resoiltwin/commit/2448f6558c9846afaf5b5829dc17d1547c2398dd))
* replace a constraint count that goes stale with the invariant itself ([a7a1023](https://github.com/EuroUnionConsult/resoiltwin/commit/a7a1023989bf8f9a036d4f735877544734c7d687))
* rewrite readme for a public audience ([a43bfd6](https://github.com/EuroUnionConsult/resoiltwin/commit/a43bfd680cd48708a8139fbff97faa178c7fe8cd))
* separate what the SCL mask confirms from what it cannot measure ([44090ea](https://github.com/EuroUnionConsult/resoiltwin/commit/44090eaf5266141a952ee12d4105d553d80e4dcd))
* tighten claims on deduplication key, cloud cover and pixel counts ([e2016a7](https://github.com/EuroUnionConsult/resoiltwin/commit/e2016a7b0c299370907e02eb12c132cd6adf067a))

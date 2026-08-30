# Changelog

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

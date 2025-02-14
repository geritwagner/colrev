#! /usr/bin/env python
"""SearchSource: LocalIndex"""
from __future__ import annotations

import difflib
import typing
import webbrowser
from multiprocessing import Lock
from pathlib import Path
from urllib.parse import urlparse

import git
from pydantic import Field

import colrev.env.local_index
import colrev.exceptions as colrev_exceptions
import colrev.ops.check
import colrev.package_manager.interfaces
import colrev.package_manager.package_manager
import colrev.package_manager.package_settings
import colrev.record.record
from colrev.constants import Colors
from colrev.constants import Fields
from colrev.constants import FieldSet
from colrev.constants import FieldValues
from colrev.constants import RecordState
from colrev.constants import SearchSourceHeuristicStatus
from colrev.constants import SearchType

# pylint: disable=unused-argument
# pylint: disable=duplicate-code


class LocalIndexSearchSource(colrev.package_manager.interfaces.SearchSourceInterface):
    """LocalIndex"""

    # pylint: disable=too-many-instance-attributes

    settings_class = colrev.package_manager.package_settings.DefaultSourceSettings
    source_identifier = Fields.CURATION_ID
    search_types = [SearchType.API, SearchType.MD]
    endpoint = "colrev.local_index"

    ci_supported: bool = Field(default=True)
    heuristic_status = SearchSourceHeuristicStatus.supported

    _local_index_md_filename = Path("data/search/md_curated.bib")

    essential_md_keys = [
        Fields.TITLE,
        Fields.AUTHOR,
        Fields.JOURNAL,
        Fields.YEAR,
        Fields.BOOKTITLE,
        Fields.NUMBER,
        Fields.VOLUME,
        Fields.AUTHOR,
        Fields.DOI,
        Fields.DBLP_KEY,
        Fields.URL,
    ]

    def __init__(
        self,
        *,
        source_operation: colrev.process.operation.Operation,
        settings: typing.Optional[dict] = None,
    ) -> None:
        self.review_manager = source_operation.review_manager
        if settings:
            # LocalIndex as a search_source
            self.search_source = self.settings_class(**settings)

        else:
            # LocalIndex as an md-prep source
            li_md_source_l = [
                s
                for s in self.review_manager.settings.sources
                if s.filename == self._local_index_md_filename
            ]
            if li_md_source_l:
                self.search_source = li_md_source_l[0]
            else:
                self.search_source = colrev.settings.SearchSource(
                    endpoint=self.endpoint,
                    filename=self._local_index_md_filename,
                    search_type=SearchType.MD,
                    search_parameters={},
                    comment="",
                )

            self.local_index_lock = Lock()

        self.origin_prefix = self.search_source.get_origin_prefix()

        self.local_index = colrev.env.local_index.LocalIndex(
            verbose_mode=self.review_manager.verbose_mode
        )

    def _validate_source(self) -> None:
        """Validate the SearchSource (parameters etc.)"""
        source = self.search_source
        self.review_manager.logger.debug(f"Validate SearchSource {source.filename}")

        assert source.search_type in self.search_types

        # if "query" not in source.search_parameters:
        # Note :  for md-sources, there is no query parameter.
        #     raise colrev_exceptions.InvalidQueryException(
        #         f"Source missing query search_parameter ({source.filename})"
        #     )

        if "query" in source.search_parameters:
            pass
            # if "simple_query_string" in source.search_parameters["query"]:
            #     if "query" in source.search_parameters["query"]["simple_query_string"]:
            #         pass
            #     else:
            #         raise colrev_exceptions.InvalidQueryException(
            #             "Source missing query/simple_query_string/query "
            #             f"search_parameter ({source.filename})"
            #         )

            # elif "url" in source.search_parameters["query"]:
            #     pass
            # # else:
            #     raise colrev_exceptions.InvalidQueryException(
            #         f"Source missing query/query search_parameter ({source.filename})"
            #     )

        self.review_manager.logger.debug(f"SearchSource {source.filename} validated")

    def _retrieve_from_index(self) -> typing.List[dict]:
        params = self.search_source.search_parameters
        query = params["query"]

        if not any(x in query for x in [Fields.TITLE, Fields.ABSTRACT]):
            query = f'title LIKE "%{query}%"'

        returned_records = self.local_index.search(query)

        records_to_import = [r.get_data() for r in returned_records]
        records_to_import = [r for r in records_to_import if r]
        keys_to_drop = [
            Fields.STATUS,
            Fields.ORIGIN,
            Fields.SCREENING_CRITERIA,
        ]
        for record_dict in records_to_import:
            record_dict = {
                key: value
                for key, value in record_dict.items()
                if key not in keys_to_drop
            }

        return records_to_import

    def _run_md_search(
        self,
        *,
        local_index_feed: colrev.ops.search_api_feed.SearchAPIFeed,
    ) -> None:

        for feed_record_dict in list(local_index_feed.feed_records.values()):
            try:
                retrieved_record = self.local_index.retrieve(
                    record_dict=feed_record_dict, include_file=False
                )
                local_index_feed.add_update_record(retrieved_record)
            except (
                colrev_exceptions.RecordNotInIndexException,
                colrev_exceptions.NotFeedIdentifiableException,
            ):
                continue

        for record_dict in local_index_feed.records.values():
            record = colrev.record.record.Record(record_dict)
            record.remove_field(key="colrev.local_index.curation_ID")

        local_index_feed.save()

    def _run_api_search(
        self,
        *,
        local_index_feed: colrev.ops.search_api_feed.SearchAPIFeed,
    ) -> None:

        for retrieved_record_dict in self._retrieve_from_index():
            try:
                retrieved_record = colrev.record.record.Record(retrieved_record_dict)
                local_index_feed.add_update_record(retrieved_record)
            except colrev_exceptions.NotFeedIdentifiableException:
                continue

        for record_dict in local_index_feed.feed_records.values():
            record_dict.pop("colrev.local_index.curation_ID", None)
            record_dict.pop("curation_ID", None)
        for record_dict in local_index_feed.records.values():
            record_dict.pop("colrev.local_index.curation_ID", None)
            record_dict.pop("curation_ID", None)

        local_index_feed.save()

    def search(self, rerun: bool) -> None:
        """Run a search of local-index"""

        self._validate_source()

        local_index_feed = self.search_source.get_api_feed(
            review_manager=self.review_manager,
            source_identifier=self.source_identifier,
            update_only=(not rerun),
        )

        if self.search_source.search_type == SearchType.MD:
            self._run_md_search(local_index_feed=local_index_feed)

        elif self.search_source.search_type in [
            SearchType.API,
            SearchType.TOC,
        ]:
            self._run_api_search(
                local_index_feed=local_index_feed,
            )
        else:
            raise NotImplementedError

    @classmethod
    def heuristic(cls, filename: Path, data: str) -> dict:
        """Source heuristic for local-index"""

        result = {"confidence": 0.0}
        if Fields.CURATION_ID in data:
            result["confidence"] = 1.0

        return result

    @classmethod
    def add_endpoint(
        cls,
        operation: colrev.ops.search.Search,
        params: str,
    ) -> colrev.settings.SearchSource:
        """Add SearchSource as an endpoint (based on query provided to colrev search --add )"""

        # always API search

        if len(params) == 0:
            search_source = operation.create_api_source(endpoint=cls.endpoint)
        else:
            filename = operation.get_unique_filename(
                file_path_string=f"local_index_{params}".replace("%", "").replace(
                    "'", ""
                )
            )
            search_source = colrev.settings.SearchSource(
                endpoint=cls.endpoint,
                filename=filename,
                search_type=SearchType.API,
                search_parameters={"query": params},
                comment="",
            )
        operation.add_source_and_search(search_source)
        return search_source

    def load(self, load_operation: colrev.ops.load.Load) -> dict:
        """Load the records from the SearchSource file"""

        if self.search_source.filename.suffix == ".bib":

            def field_mapper(record_dict: dict) -> None:
                if "link" in record_dict:
                    if "url" in record_dict:
                        del record_dict["link"]
                    else:
                        record_dict[Fields.URL] = record_dict.pop("link")
                for key in list(record_dict.keys()):
                    if key not in FieldSet.STANDARDIZED_FIELD_KEYS:
                        self.review_manager.logger.debug(
                            f"Field {key} not in standard field set"
                        )
                        del record_dict[key]

            records = colrev.loader.load_utils.load(
                filename=self.search_source.filename,
                field_mapper=field_mapper,
                logger=self.review_manager.logger,
            )
            for record_id in records:
                record_dict = {
                    k: v
                    for k, v in records[record_id].items()
                    if k not in FieldSet.PROVENANCE_KEYS + [Fields.SCREENING_CRITERIA]
                }

                if Fields.CURATION_ID in record_dict:
                    record_dict[Fields.MD_PROV] = {
                        FieldValues.CURATED: {
                            "source": record_dict[Fields.CURATION_ID].split("#")[0],
                            "note": "",
                        }
                    }
                records[record_id] = record_dict

            return records

        raise NotImplementedError

    def prepare(
        self, record: colrev.record.record.Record, source: colrev.settings.SearchSource
    ) -> colrev.record.record.Record:
        """Source-specific preparation for local-index"""

        return record

    def _add_cpid(self, *, record: colrev.record.record.Record) -> bool:
        # To enable retrieval based on colrev_pdf_id (as part of the global_ids)
        if Fields.FILE in record.data and "colrev_pdf_id" not in record.data:
            pdf_path = Path(self.review_manager.path / Path(record.data[Fields.FILE]))
            if pdf_path.is_file():
                try:
                    record.data.update(
                        colrev_pdf_id=colrev.record.record.Record.get_colrev_pdf_id(
                            pdf_path,
                        )
                    )
                    return True
                except colrev_exceptions.PDFHashError:
                    pass
        return False

    def _retrieve_record_from_local_index(
        self,
        record: colrev.record.record.Record,
    ) -> colrev.record.record.Record:
        # add colrev_pdf_id
        added_colrev_pdf_id = self._add_cpid(record=record)

        try:
            retrieved_record = self.local_index.retrieve(
                record_dict=record.get_data(), include_file=False
            )
        except (
            colrev_exceptions.RecordNotInIndexException,
            colrev_exceptions.NotEnoughDataToIdentifyException,
        ):
            try:
                # Search within the table-of-content in local_index
                retrieved_record = self.local_index.retrieve_from_toc(
                    record,
                    include_file=False,
                )
            except colrev_exceptions.RecordNotInTOCException:
                return record

            except colrev_exceptions.RecordNotInIndexException:
                try:
                    # Search across table-of-contents in local_index
                    retrieved_record = self.local_index.retrieve_from_toc(
                        record,
                        include_file=False,
                        search_across_tocs=True,
                    )
                except (
                    colrev_exceptions.RecordNotInIndexException,
                    colrev_exceptions.RecordNotInTOCException,
                ):
                    return record
            except colrev_exceptions.NotTOCIdentifiableException:
                return record
        finally:
            if added_colrev_pdf_id:
                del record.data["colrev_pdf_id"]

        if Fields.STATUS in retrieved_record.data:
            del retrieved_record.data[Fields.STATUS]

        return retrieved_record

    def _store_retrieved_record_in_feed(
        self,
        *,
        record: colrev.record.record.Record,
        retrieved_record: colrev.record.record.Record,
        prep_operation: colrev.ops.prep.Prep,
    ) -> None:
        try:
            default_source = retrieved_record.get_field_provenance_source(
                FieldValues.CURATED
            )
            if default_source == "":
                default_source = "LOCAL_INDEX"

            # lock: to prevent different records from having the same origin
            self.local_index_lock.acquire(timeout=60)

            # Note : need to reload file because the object is not shared between processes
            local_index_feed = self.search_source.get_api_feed(
                review_manager=self.review_manager,
                source_identifier=self.source_identifier,
                update_only=False,
                prep_mode=True,
            )

            local_index_feed.add_update_record(retrieved_record)

            retrieved_record.remove_field(key=Fields.CURATION_ID)

            record.merge(
                retrieved_record,
                default_source=default_source,
            )

            # If volume/number are no longer in the CURATED record
            if (
                Fields.NUMBER in record.data
                and Fields.NUMBER not in retrieved_record.data
            ):
                del record.data[Fields.NUMBER]
            if (
                Fields.VOLUME in record.data
                and Fields.VOLUME not in retrieved_record.data
            ):
                del record.data[Fields.VOLUME]

            record.set_masterdata_curated(source=default_source)
            record.set_status(RecordState.md_prepared)
            if (
                record.data.get(Fields.PRESCREEN_EXCLUSION, "NA")
                == FieldValues.RETRACTED
            ):
                record.prescreen_exclude(reason=FieldValues.RETRACTED)

            git_repo = self.review_manager.dataset.get_repo()
            cur_project_source_paths = [str(self.review_manager.path)]
            for remote in git_repo.remotes:
                if remote.url:
                    shared_url = remote.url
                    shared_url = shared_url.rstrip(".git")
                    cur_project_source_paths.append(shared_url)
                    break

            try:
                local_index_feed.save()
                # extend fields_to_keep (to retrieve all fields from the index)
                for key in record.data.keys():
                    if key not in prep_operation.fields_to_keep:
                        prep_operation.fields_to_keep.append(key)

            except OSError:
                pass
        except colrev_exceptions.NotFeedIdentifiableException:
            print("not-feed-identifiable")
        finally:
            self.local_index_lock.release()

    def prep_link_md(
        self,
        prep_operation: colrev.ops.prep.Prep,
        record: colrev.record.record.Record,
        save_feed: bool = True,
        timeout: int = 10,
    ) -> colrev.record.record.Record:
        """Retrieve masterdata from LocalIndex based on similarity with the record provided"""

        retrieved_record = self._retrieve_record_from_local_index(record)

        # restriction: if we don't restrict to CURATED,
        # we may have to rethink the LocalIndexSearchFeed.set_ids()
        if not retrieved_record.masterdata_is_curated():
            return record

        self._store_retrieved_record_in_feed(
            record=record,
            retrieved_record=retrieved_record,
            prep_operation=prep_operation,
        )

        return record

    def _get_local_base_repos(self, *, change_itemsets: list) -> dict:
        base_repos = []
        for item in change_itemsets:
            repo_path = colrev.record.record.Record(
                item["original_record"]
            ).get_field_provenance_source(FieldValues.CURATED)
            if repo_path != "":
                assert "#" not in repo_path
                # otherwise: strip the ID at the end if we add an ID...
                base_repos.append(repo_path)

        base_repos = list(set(base_repos))
        environment_manager = colrev.env.environment_manager.EnvironmentManager()
        local_base_repos = {
            x["repo_source_url"]: x["repo_source_path"]
            for x in environment_manager.local_repos()
            if x.get("repo_source_url", "NA") in base_repos
        }
        return local_base_repos

    def _print_changes(self, *, local_base_repo: str, change_itemsets: list) -> list:
        def print_diff(change: tuple) -> str:
            diff = difflib.Differ()
            letters = list(diff.compare(change[1], change[0]))
            for i, letter in enumerate(letters):
                if letter.startswith("  "):
                    letters[i] = letters[i][-1]
                elif letter.startswith("+ "):
                    letters[i] = f"{Colors.RED}" + letters[i][-1] + f"{Colors.END}"
                elif letter.startswith("- "):
                    letters[i] = f"{Colors.GREEN}" + letters[i][-1] + f"{Colors.END}"
            res = "".join(letters).replace("\n", " ")
            return res

        selected_changes = []
        print()
        self.review_manager.logger.info(f"Base repository: {local_base_repo}")
        for item in change_itemsets:
            repo_path = colrev.record.record.Record(
                item["original_record"]
            ).get_field_provenance_source(FieldValues.CURATED)
            assert "#" not in repo_path

            if repo_path != local_base_repo:
                continue

            # self.review_manager.p_printer.pprint(item["original_record"])
            colrev.record.record.Record(item["original_record"]).print_citation_format()
            for change_item in item["changes"]:
                if change_item[0] == "change":
                    edit_type, field, values = change_item
                    if field == "colrev_id":
                        continue
                    prefix = f"{edit_type} {field}"
                    print(
                        f"{prefix}"
                        + " " * max(len(prefix), 30 - len(prefix))
                        + f": {values[0]}"
                    )
                    print(
                        " " * max(len(prefix), 30)
                        + f"  {Colors.ORANGE}{values[1]}{Colors.END}"
                    )
                    print(
                        " " * max(len(prefix), 30)
                        + f"  {print_diff((values[0], values[1]))}"
                    )

                elif change_item[0] == "add":
                    edit_type, field, values = change_item
                    prefix = f"{edit_type} {values[0][0]}"
                    print(
                        prefix
                        + " " * max(len(prefix), 30 - len(prefix))
                        + f": {Colors.GREEN}{values[0][1]}{Colors.END}"
                    )
                else:
                    self.review_manager.p_printer.pprint(change_item)
            selected_changes.append(item)
        return selected_changes

    def apply_correction(self, *, change_itemsets: list) -> None:
        """Apply a correction by opening a pull request in the original repository"""

        local_base_repos = self._get_local_base_repos(change_itemsets=change_itemsets)

        for local_base_repo_url, local_base_repo_path in local_base_repos.items():
            selected_changes = self._print_changes(
                local_base_repo=local_base_repo_url, change_itemsets=change_itemsets
            )

            response = ""
            while True:
                response = input("\nConfirm changes? (y/n)")
                if response in ["y", "n"]:
                    break

            if response == "y":
                self._apply_correction(
                    source_url=local_base_repo_path,
                    change_list=selected_changes,
                )
            elif response == "n":
                if input("Discard all corrections (y/n)?") == "y":
                    for selected_change in selected_changes:
                        Path(selected_change[Fields.FILE]).unlink()

    def _apply_corrections_precondition(
        self, *, check_operation: colrev.process.operation.Operation, source_url: str
    ) -> bool:
        git_repo = check_operation.review_manager.dataset.get_repo()

        if git_repo.is_dirty():
            msg = f"Repo not clean ({source_url}): commit or stash before updating records"
            raise colrev_exceptions.CorrectionPreconditionException(msg)

        if check_operation.review_manager.dataset.behind_remote():
            origin = git_repo.remotes.origin
            origin.pull()
            if not check_operation.review_manager.dataset.behind_remote():
                self.review_manager.logger.info("Pulled changes")
            else:
                self.review_manager.logger.error(
                    "Repo behind remote. Pull first to avoid conflicts.\n"
                    "colrev env --pull"
                )
                return False

        return True

    def _retrieve_by_colrev_id(
        self, *, indexed_record_dict: dict, records: list[dict]
    ) -> dict:
        indexed_record = colrev.record.record.Record(indexed_record_dict)

        # if "colrev_id" in indexed_record.data:
        #     cid_to_retrieve = indexed_record.get_colrev_id()
        # else:
        #     cid_to_retrieve = [indexed_record.get_colrev_id()]
        cid_to_retrieve = [indexed_record.get_colrev_id()]

        record_l = [
            x
            for x in records
            if any(
                cid in colrev.record.record.Record(x).get_colrev_id()
                for cid in cid_to_retrieve
            )
        ]
        if len(record_l) != 1:
            raise colrev_exceptions.RecordNotInRepoException(
                indexed_record.data[Fields.ID]
            )
        return record_l[0]

    def _retrieve_record_for_correction(
        self,
        *,
        records: dict,
        change_item: dict,
    ) -> dict:
        original_record = change_item["original_record"]

        local_index_feed = self.search_source.get_api_feed(
            review_manager=self.review_manager,
            source_identifier=self.source_identifier,
            update_only=True,
        )

        try:
            md_curated_origin_id = [
                x for x in original_record[Fields.ORIGIN] if "md_curated.bib/" in x
            ][0].replace("md_curated.bib/", "")
            curation_origin_record = local_index_feed.feed_records[md_curated_origin_id]
            curation_id = curation_origin_record[Fields.CURATION_ID]
            curation_id = curation_id[curation_id.find("#") + 1 :]
            return records[curation_id]
        except KeyError:
            pass

        try:
            record_dict = self._retrieve_by_colrev_id(
                indexed_record_dict=original_record,
                records=list(records.values()),
            )
            return record_dict
        except colrev_exceptions.RecordNotInRepoException:
            matching_doi_rec_l = [
                r
                for r in records.values()
                if original_record.get(Fields.DOI, "NDOI") == r.get(Fields.DOI, "NA")
            ]
            if len(matching_doi_rec_l) == 1:
                record_dict = matching_doi_rec_l[0]
                return record_dict

            matching_url_rec_l = [
                r
                for r in records.values()
                if original_record.get(Fields.URL, "NURL") == r.get(Fields.URL, "NA")
            ]
            if len(matching_url_rec_l) == 1:
                record_dict = matching_url_rec_l[0]
                return record_dict

        self.review_manager.logger.error(
            f"{Colors.RED}Record not found: {original_record[Fields.ID]}{Colors.END}"
        )
        raise colrev_exceptions.RecordNotInIndexException(original_record[Fields.ID])

    def _create_correction_branch(
        self, *, git_repo: git.Repo, record_dict: dict
    ) -> str:
        record_branch_name = record_dict[Fields.ID]
        counter = 1
        new_record_branch_name = record_branch_name
        while new_record_branch_name in [ref.name for ref in git_repo.references]:
            new_record_branch_name = f"{record_branch_name}_{counter}"
            counter += 1

        record_branch_name = new_record_branch_name
        git_repo.git.branch(record_branch_name)
        return record_branch_name

    def _apply_record_correction(
        self,
        *,
        check_operation: colrev.process.operation.Operation,
        records: dict,
        record_dict: dict,
        change_item: dict,
    ) -> None:
        for edit_type, key, change in list(change_item["changes"]):
            # Note : by retricting changes to self.essential_md_keys,
            # we also prevent changes in
            # Fields.STATUS, Fields.ORIGIN, Fields.FILE

            # Note: the most important thing is to update the metadata.

            if edit_type == "change":
                if key not in self.essential_md_keys:
                    continue
                record_dict[key] = change[1]
            if edit_type == "add":
                key = change[0][0]
                value = change[0][1]
                if key not in self.essential_md_keys:
                    continue
                record_dict[key] = value
            # gh_issue https://github.com/CoLRev-Environment/colrev/issues/63
            # deal with remove/merge

        check_operation.review_manager.dataset.save_records_dict(records)
        check_operation.review_manager.dataset.create_commit(
            msg=f"Update {record_dict['ID']}", script_call="colrev push"
        )

    def _push_corrections_and_reset_branch(
        self,
        *,
        git_repo: git.Repo,
        record_branch_name: str,
        prev_branch_name: str,
        source_url: str,
    ) -> None:
        git_repo.remotes.origin.push(
            refspec=f"{record_branch_name}:{record_branch_name}"
        )
        self.review_manager.logger.info("Pushed corrections")

        for head in git_repo.heads:
            if head.name == prev_branch_name:
                head.checkout()

        git_repo = git.Git(source_url)
        git_repo.execute(["git", "branch", "-D", record_branch_name])

        self.review_manager.logger.info("Removed local corrections branch")

    def _reset_record_after_correction(
        self, *, record_dict: dict, rec_for_reset: dict, change_item: dict
    ) -> None:
        # reset the record - each branch should have changes for one record
        # Note : modify dict (do not replace it) - otherwise changes will not be
        # part of the records.
        for key, value in rec_for_reset.items():
            record_dict[key] = value
        keys_added = [
            key for key in record_dict.keys() if key not in rec_for_reset.keys()
        ]
        for key in keys_added:
            del record_dict[key]

        if Path(change_item[Fields.FILE]).is_file():
            Path(change_item[Fields.FILE]).unlink()

    def _apply_change_item_correction(
        self,
        *,
        check_operation: colrev.process.operation.Operation,
        source_url: str,
        change_list: list,
    ) -> bool:
        # pylint: disable=too-many-locals

        git_repo = check_operation.review_manager.dataset.get_repo()
        records = check_operation.review_manager.dataset.load_records_dict()

        success = False
        pull_request_msgs = []
        pull_request_links = []
        for change_item in change_list:
            try:
                record_dict = self._retrieve_record_for_correction(
                    records=records,
                    change_item=change_item,
                )
                if not record_dict:
                    continue

                record_branch_name = self._create_correction_branch(
                    git_repo=git_repo, record_dict=record_dict
                )
                prev_branch_name = git_repo.active_branch.name

                remote = git_repo.remote()
                for head in git_repo.heads:
                    if head.name == record_branch_name:
                        head.checkout()

                rec_for_reset = record_dict.copy()

                self._apply_record_correction(
                    check_operation=check_operation,
                    records=records,
                    record_dict=record_dict,
                    change_item=change_item,
                )

                self._push_corrections_and_reset_branch(
                    git_repo=git_repo,
                    record_branch_name=record_branch_name,
                    prev_branch_name=prev_branch_name,
                    source_url=source_url,
                )

                self._reset_record_after_correction(
                    record_dict=record_dict,
                    rec_for_reset=rec_for_reset,
                    change_item=change_item,
                )

                host = urlparse(remote.url).hostname
                if host and host.endswith("github.com"):
                    link = (
                        str(remote.url).rstrip(".git")
                        + "/compare/"
                        + record_branch_name
                    )
                    pull_request_links.append(link)
                    pull_request_msgs.append(
                        "\nTo create a pull request for your changes go "
                        f"to \n{Colors.ORANGE}{link}{Colors.END}"
                    )
                success = True
            except colrev_exceptions.RecordNotInIndexException:
                pass

        for pull_request_msg in pull_request_msgs:
            print(pull_request_msg)
        for pull_request_link in pull_request_links:
            webbrowser.open(pull_request_link, new=2)

        # https://github.com/geritwagner/information_systems_papers/compare/update?expand=1
        # gh_issue https://github.com/CoLRev-Environment/colrev/issues/63
        # handle cases where update branch already exists
        return success

    def _apply_correction(self, *, source_url: str, change_list: list) -> None:
        """Apply a (list of) corrections"""

        # TBD: other modes of accepting changes?
        # e.g., only-metadata, no-changes, all(including optional fields)
        check_review_manager = self.review_manager.get_connecting_review_manager(
            path_str=source_url
        )
        check_operation = colrev.ops.check.CheckOperation(check_review_manager)

        if check_review_manager.dataset.behind_remote():
            git_repo = check_review_manager.dataset.get_repo()
            origin = git_repo.remotes.origin
            self.review_manager.logger.info(
                f"Pull project changes from {git_repo.remotes.origin}"
            )
            res = origin.pull()
            self.review_manager.logger.info(res)

        try:
            if not self._apply_corrections_precondition(
                check_operation=check_operation, source_url=source_url
            ):
                return
        except colrev_exceptions.CorrectionPreconditionException as exc:
            print(exc)
            return

        check_review_manager.logger.info(
            "Precondition for correction (pull-request) checked."
        )

        success = self._apply_change_item_correction(
            check_operation=check_operation,
            source_url=source_url,
            change_list=change_list,
        )

        if success:
            print(
                f"\n{Colors.GREEN}Thank you for supporting other researchers "
                f"by sharing your corrections ❤{Colors.END}\n"
            )

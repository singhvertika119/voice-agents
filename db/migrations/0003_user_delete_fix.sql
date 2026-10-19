-- Bug found by the isolation test cleanup: deleting a user failed with HTTP 500 because
-- agent_versions.created_by referenced auth.users with no ON DELETE rule. Account deletion
-- (DPDP erasure) must work, so keep the version and forget who created it.
alter table agent_versions drop constraint agent_versions_created_by_fkey;
alter table agent_versions
  add constraint agent_versions_created_by_fkey
  foreign key (created_by) references auth.users(id) on delete set null;

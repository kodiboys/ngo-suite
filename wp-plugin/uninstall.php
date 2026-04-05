<?php
/**
 * FILE: wp-plugin/uninstall.php
 * MODULE: Plugin Uninstall - Clean up database tables
 */

if (!defined('WP_UNINSTALL_PLUGIN')) {
    exit;
}

global $wpdb;

// Delete custom tables
$wpdb->query("DROP TABLE IF EXISTS {$wpdb->prefix}trueangels_audit");

// Delete options
delete_option('trueangels_api_url');
delete_option('trueangels_api_key');
delete_option('trueangels_default_project');
delete_option('trueangels_enable_audit');
delete_option('trueangels_cache_duration');

// Clear scheduled cron jobs
wp_clear_scheduled_hook('trueangels_sync_donations');
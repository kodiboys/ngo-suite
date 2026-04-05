<?php
/**
 * FILE: wp-plugin/includes/class-api-client.php
 * MODULE: API Client für TrueAngels Backend
 */

class TrueAngels_APIClient {
    
    private $api_url;
    private $api_key;
    private $timeout = 30;
    
    public function __construct($api_url, $api_key) {
        $this->api_url = rtrim($api_url, '/');
        $this->api_key = $api_key;
    }
    
    public function get($endpoint, $params = []) {
        $url = $this->api_url . '/api/v1' . $endpoint;
        
        if (!empty($params)) {
            $url .= '?' . http_build_query($params);
        }
        
        $response = wp_remote_get($url, [
            'timeout' => $this->timeout,
            'headers' => $this->get_headers()
        ]);
        
        return $this->handle_response($response);
    }
    
    public function post($endpoint, $data = []) {
        $url = $this->api_url . '/api/v1' . $endpoint;
        
        $response = wp_remote_post($url, [
            'timeout' => $this->timeout,
            'headers' => $this->get_headers(),
            'body' => json_encode($data)
        ]);
        
        return $this->handle_response($response);
    }
    
    public function put($endpoint, $data = []) {
        $url = $this->api_url . '/api/v1' . $endpoint;
        
        $response = wp_remote_request($url, [
            'method' => 'PUT',
            'timeout' => $this->timeout,
            'headers' => $this->get_headers(),
            'body' => json_encode($data)
        ]);
        
        return $this->handle_response($response);
    }
    
    public function delete($endpoint) {
        $url = $this->api_url . '/api/v1' . $endpoint;
        
        $response = wp_remote_request($url, [
            'method' => 'DELETE',
            'timeout' => $this->timeout,
            'headers' => $this->get_headers()
        ]);
        
        return $this->handle_response($response);
    }
    
    private function get_headers() {
        return [
            'Authorization' => 'Bearer ' . $this->api_key,
            'Content-Type' => 'application/json',
            'Accept' => 'application/json',
            'X-WP-Integration' => 'trueangels-wordpress',
            'X-WP-Version' => get_bloginfo('version')
        ];
    }
    
    private function handle_response($response) {
        if (is_wp_error($response)) {
            throw new Exception($response->get_error_message());
        }
        
        $status_code = wp_remote_retrieve_response_code($response);
        $body = wp_remote_retrieve_body($response);
        $data = json_decode($body, true);
        
        if ($status_code >= 400) {
            $error_message = isset($data['detail']) ? $data['detail'] : 'API request failed';
            throw new Exception($error_message, $status_code);
        }
        
        return $data;
    }
}
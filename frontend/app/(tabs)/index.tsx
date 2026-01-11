// app/(tabs)/index.tsx

import { useBottomTabBarHeight } from "@react-navigation/bottom-tabs";
import { useEffect, useRef, useState } from "react";
import {
  Dimensions,
  FlatList,
  ListRenderItemInfo,
  Platform,
  View,
  Text,
  Pressable,
  StyleSheet,
  Share,
  ActivityIndicator,
  ViewStyle,
} from "react-native";

import { VideoView, useVideoPlayer } from "expo-video";
import { Audio } from "expo-av";
import { ReelOverlay } from "../../components/ReelOverlay";
import { OTPInputModal } from "../../components/OTPInputModal";
import { Ionicons } from "@expo/vector-icons";
import Config from "../../config";

const { height, width } = Dimensions.get("window");

// ✅ Kill-switch: set EXPO_PUBLIC_DISABLE_FEED=true to stop ALL video/network logic
const DISABLE_FEED = process.env.EXPO_PUBLIC_DISABLE_FEED === "true";
console.log("🚦 FEED STATUS:", DISABLE_FEED ? "DISABLED (AUTH MODE)" : "ENABLED");

// Helper function to normalize URLs (remove trailing slashes)
const normalizeUrl = (url: string): string => {
  return url.replace(/\/+$/, "");
};

// Configuration pulled from environment variables
const API_BASE_URL = normalizeUrl(
  process.env.EXPO_PUBLIC_API_BASE_URL || "http://localhost:8000"
);

// Video service URL - defaults to same host as backend but port 8002
const getVideoServiceUrl = () => {
  const baseUrl = normalizeUrl(
    process.env.EXPO_PUBLIC_API_BASE_URL || "http://localhost:8000"
  );

  if (process.env.EXPO_PUBLIC_VIDEO_SERVICE_URL) {
    return normalizeUrl(process.env.EXPO_PUBLIC_VIDEO_SERVICE_URL);
  }

  // Extract host from base URL and change port to 8002
  try {
    const url = new URL(baseUrl);
    return `${url.protocol}//${url.hostname}:8002`;
  } catch {
    return "http://localhost:8002";
  }
};
const VIDEO_SERVICE_URL = getVideoServiceUrl();

// Log configuration on startup
console.log("🔧 API Configuration:");
console.log("  API_BASE_URL:", API_BASE_URL);
console.log("  VIDEO_SERVICE_URL:", VIDEO_SERVICE_URL);
console.log(
  "  EXPO_PUBLIC_API_BASE_URL:",
  process.env.EXPO_PUBLIC_API_BASE_URL || "(not set, using default)"
);

// Hardcoded sample user ID for testing
const SAMPLE_USER_ID = "sample-user-123";

// Hardcoded test video IDs for testing (these are actual video IDs in DigitalOcean Spaces)
const TEST_VIDEO_IDS = [
  "48561bf3",
  "48562485",
  "48562a69",
  "48562c60",
  "48563e71",
  "48563ec4",
  "48564cb2",
  "48564d21",
  "48565024",
  "48565185",
  "48565f15",
  "485664b7",
  "4856895c",
  "4856a00d",
  "4856aa09",
  "4856bac1",
  "4856bb17",
  "4856d458",
  "4856ef20",
  "4856f32c",
];

// Function to fetch videos using semantic search
async function fetchVideosFromSemanticSearch(
  resetIfEmpty: boolean = false
): Promise<string[]> {
  // ✅ Hard guard: if feed disabled, return immediately with no network calls
  if (DISABLE_FEED) return [];

  try {
    // For testing: use hardcoded test video IDs
    console.log("🧪 Using test video IDs for testing");
    let videoIds: string[] = [...TEST_VIDEO_IDS];

    console.log(
      `Found ${videoIds.length} video IDs (greenhouse_ids), fetching HLS URLs...`
    );

    // Step 2: For each video_id (greenhouse_id), call video service to get HLS playback URL
    console.log(`📹 Video Service URL: ${VIDEO_SERVICE_URL}`);
    console.log(`📹 Fetching HLS URLs for ${videoIds.length} videos...`);

    const videoUrls = await Promise.all(
      videoIds.map(async (videoId: string) => {
        const videoUrl = `${VIDEO_SERVICE_URL}/video/${videoId}`;
        console.log(`  🔍 Fetching HLS URL for video ${videoId}`);
        console.log(`     URL: ${videoUrl}`);

        const startTime = Date.now();
        try {
          const videoResponse = await fetch(videoUrl, {
            method: "GET",
            headers: {
              Accept: "application/json",
            },
          });

          const elapsed = Date.now() - startTime;
          console.log(`     ✅ Response received in ${elapsed}ms`);
          console.log(
            `     Status: ${videoResponse.status} ${videoResponse.statusText}`
          );

          if (!videoResponse.ok) {
            console.error(
              `     ❌ HTTP error ${videoResponse.status} for video ${videoId}`
            );
            // Try to get error details
            try {
              const errorText = await videoResponse.text();
              console.error(`     Error body: ${errorText.substring(0, 200)}`);
            } catch (e) {
              console.error(`     Could not read error response`);
            }
            return null;
          }

          const videoData = await videoResponse.json();
          console.log(
            `     Response data:`,
            JSON.stringify(videoData).substring(0, 150)
          );

          // Extract playback.url from response
          const playbackUrl = videoData.playback?.url || videoData.url;

          if (!playbackUrl) {
            console.warn(
              `     ⚠️  No playback URL found for video ${videoId}`
            );
            console.warn(`     Available keys:`, Object.keys(videoData));
            return null;
          }

          console.log(`     ✅ Got playback URL: ${playbackUrl}`);
          return playbackUrl;
        } catch (error: any) {
          const elapsed = Date.now() - startTime;
          console.error(
            `     ❌ Error after ${elapsed}ms for video ${videoId}:`
          );
          console.error(`     Error type: ${error?.name || "Unknown"}`);
          console.error(
            `     Error message: ${error?.message || String(error)}`
          );
          console.error(`     URL attempted: ${videoUrl}`);
          console.error(`     This usually means:`);
          console.error(
            `       - Video service is not running on ${VIDEO_SERVICE_URL}`
          );
          console.error(
            `       - Video service endpoint /video/${videoId} doesn't exist`
          );
          console.error(
            `       - Network/firewall blocking access to port 8002`
          );
          return null;
        }
      })
    );

    // Filter out null values (failed fetches)
    const validUrls = videoUrls.filter((url): url is string => url !== null);

    console.log(`Loaded ${validUrls.length} HLS URLs`);
    return validUrls;
  } catch (error: any) {
    console.error("❌ Fatal error in fetchVideosFromSemanticSearch:");
    console.error("  Error type:", error?.name || "Unknown");
    console.error("  Error message:", error?.message || String(error));
    console.error("  Stack:", error?.stack || "No stack trace");
    console.error("  This suggests a network/connectivity issue with the backend");
    return [];
  }
}

interface VideoWrapperProps {
  data: ListRenderItemInfo<string>;
  allVideos: string[];
  visibleIndex: number;
  pause: () => void;
  share: (videoURL: string) => void;
  pauseOverride: boolean;
}

const VideoWrapper = ({
  data,
  allVideos,
  visibleIndex,
  pause,
  pauseOverride,
  share,
}: VideoWrapperProps) => {
  const bottomHeight = useBottomTabBarHeight();
  const { index, item } = data;

  // Track if this video should be playing
  const shouldPlay = visibleIndex === index && !pauseOverride;

  // Always create player with real URL - the player handles lazy loading internally
  const player = useVideoPlayer(allVideos[index], (player) => {
    player.loop = true;
    player.muted = false;
  });

  // State for like/dislike
  const [isLiked, setIsLiked] = useState(false);
  const [isDisliked, setIsDisliked] = useState(false);
  const [likeCount, setLikeCount] = useState(12400);
  const [dislikeCount, setDislikeCount] = useState(150);

  const handleLike = () => {
    if (isLiked) {
      setIsLiked(false);
      setLikeCount(likeCount - 1);
    } else {
      setIsLiked(true);
      setLikeCount(likeCount + 1);
      if (isDisliked) {
        setIsDisliked(false);
        setDislikeCount(dislikeCount - 1);
      }
    }
  };

  const handleDislike = () => {
    if (isDisliked) {
      setIsDisliked(false);
      setDislikeCount(dislikeCount - 1);
    } else {
      setIsDisliked(true);
      setDislikeCount(dislikeCount + 1);
      if (isLiked) {
        setIsLiked(false);
        setLikeCount(likeCount - 1);
      }
    }
  };

  // Simple playback control - just play/pause based on visibility
  useEffect(() => {
    console.log(`[Video ${index}] Effect running: shouldPlay=${shouldPlay}, visibleIndex=${visibleIndex}, pauseOverride=${pauseOverride}`);
    
    if (shouldPlay) {
      console.log(`[Video ${index}] Calling player.play()`);
      try {
        player.play();
      } catch (error) {
        console.warn(`[Video ${index}] Play error:`, error);
      }
    } else {
      console.log(`[Video ${index}] Calling player.pause()`);
      try {
        player.pause();
      } catch (e) {
        console.warn(`[Video ${index}] Pause error:`, e);
      }
    }
  }, [shouldPlay, visibleIndex, pauseOverride, index]);

  // Reset video to 0:00 when scrolling away from it
  useEffect(() => {
    if (visibleIndex !== index) {
      try {
        player.currentTime = 0;
      } catch (e) {
        // Ignore reset errors
      }
    }
  }, [visibleIndex, index]);

  return (
    <View
      style={{
        height: Platform.OS === "android" ? height - bottomHeight : height,
        width,
      }}
    >
      <VideoView
        player={player}
        style={{ height: height - bottomHeight, width }}
        contentFit="cover"
        nativeControls={false}
      />

      <Pressable onPress={pause} style={$tapOverlay} />

      <ReelOverlay
        companyName="Company Name"
        title="Video Title Goes Here"
        description="This is a sample description for the video content. It can be up to two lines long."
        likeCount={likeCount}
        dislikeCount={dislikeCount}
        shareCount={3200}
        isLiked={isLiked}
        isDisliked={isDisliked}
        onLike={handleLike}
        onDislike={handleDislike}
        onShare={() => share(item)}
        onProfilePress={() => console.log("Profile pressed")}
      />

      {/* Pause indicator that sticks to this video */}
      {pauseOverride && visibleIndex === index && (
        <View style={$pauseIndicator}>
          <Ionicons name="pause" size={60} color="#fff" style={{ opacity: 0.3 }} />
        </View>
      )}
    </View>
  );
};

export default function HomeScreen() {
  const bottomHeight = useBottomTabBarHeight();

  const [allVideos, setAllVideos] = useState<string[]>([]);
  const [visibleIndex, setVisibleIndex] = useState(0);
  const [pauseOverride, setPauseOverride] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // State for email verification OTP modal
  const [showOTPModal, setShowOTPModal] = useState(false);
  const [otpCode, setOtpCode] = useState<string | null>(null);

  const prefetchedManifests = useRef<Set<string>>(new Set());

  // ✅ If feed is disabled, NEVER prefetch anything
  useEffect(() => {
    if (DISABLE_FEED) return;

    const prefetchManifests = async () => {
      const nextIndices = [visibleIndex + 1, visibleIndex + 2];
      for (const idx of nextIndices) {
        if (idx < allVideos.length && allVideos[idx]) {
          const manifestUrl = allVideos[idx];
          if (!prefetchedManifests.current.has(manifestUrl)) {
            try {
              await fetch(manifestUrl);
              prefetchedManifests.current.add(manifestUrl);
              console.log(`Prefetched manifest for video ${idx}`);
            } catch (error) {
              console.warn(`Failed to prefetch manifest ${manifestUrl}:`, error);
            }
          }
        }
      }
    };

    if (allVideos.length > 0) {
      prefetchManifests();
    }
  }, [visibleIndex, allVideos]);

  // Configure audio mode for video playback
  useEffect(() => {
    if (DISABLE_FEED) return;

    async function configureAudio() {
      try {
        await Audio.setAudioModeAsync({
          playsInSilentModeIOS: true,
          allowsRecordingIOS: false,
          interruptionModeIOS: 1, // 1 = DoNotMix (interrupt other audio)
          staysActiveInBackground: false,
          shouldDuckAndroid: true,
        });
      } catch (error) {
        console.warn("Failed to configure audio mode:", error);
      }
    }
    configureAudio();
  }, []);

  // ✅ Load initial videos from backend (GATED)
  useEffect(() => {
    if (DISABLE_FEED) {
      console.log("🛑 Feed disabled — skipping video startup");
      setLoading(false);
      setAllVideos([]);
      setError(null);
      return;
    }

    async function loadInitialVideos() {
      try {
        setLoading(true);
        const videos = await fetchVideosFromSemanticSearch(false);

        if (videos.length === 0) {
          setError("No videos found");
        } else {
          setAllVideos(videos);
        }
      } catch (err) {
        console.error("Error loading videos:", err);
        setError("Failed to load videos");
      } finally {
        setLoading(false);
      }
    }

    loadInitialVideos();
  }, []);

  const fetchMoreData = async () => {
    if (DISABLE_FEED) return;

    try {
      const moreVideos = await fetchVideosFromSemanticSearch(true);

      if (moreVideos.length > 0) {
        setAllVideos((prevVideos) => [...prevVideos, ...moreVideos]);
        console.log(
          `Added ${moreVideos.length} more videos. Total: ${
            allVideos.length + moreVideos.length
          }`
        );
      } else {
        console.log("No more videos available even after reset");
      }
    } catch (err) {
      console.error("Error fetching more videos:", err);
    }
  };

  const onViewableItemsChanged = (event: any) => {
    const lastItem = event.viewableItems.at(-1);
    if (!lastItem) return;
    
    // Extract index from key (format: "video-{index}" or just the index)
    const key = lastItem.key;
    const newIndex = key?.startsWith?.("video-") 
      ? Number(key.replace("video-", ""))
      : Number(key);
    
    if (!Number.isNaN(newIndex) && newIndex !== visibleIndex) {
      console.log(`[FlatList] Visible index changed: ${visibleIndex} → ${newIndex}`);
      setVisibleIndex(newIndex);
    }
  };

  const pause = () => {
    setPauseOverride(!pauseOverride);
  };

  const share = (videoURL: string) => {
    setPauseOverride(true);
    setTimeout(() => {
      Share.share({
        title: "Share This Video",
        message: `Check out: ${videoURL}`,
      });
    }, 100);
  };

  // ✅ AUTH MODE SCREEN (no feed mounts at all)
  if (DISABLE_FEED) {
    return (
      <View
        style={{
          flex: 1,
          backgroundColor: "black",
          justifyContent: "center",
          alignItems: "center",
          paddingHorizontal: 24,
        }}
      >
        <Text style={{ color: "#fff", fontSize: 22, fontWeight: "600" }}>
          Auth Mode
        </Text>
        <Text
          style={{
            color: "#aaa",
            marginTop: 12,
            fontSize: 14,
            textAlign: "center",
            lineHeight: 20,
          }}
        >
          Feed is disabled via EXPO_PUBLIC_DISABLE_FEED=true.
          {"\n"}
          No video services will initialize.
        </Text>
      </View>
    );
  }

  // Show loading state
  if (loading) {
    return (
      <View
        style={{
          flex: 1,
          backgroundColor: "black",
          justifyContent: "center",
          alignItems: "center",
        }}
      >
        <ActivityIndicator size="large" color="#fff" />
        <Text style={{ color: "#fff", marginTop: 20 }}>
          Loading videos...
        </Text>
      </View>
    );
  }

  // Show error state
  if (error || allVideos.length === 0) {
    return (
      <View
        style={{
          flex: 1,
          backgroundColor: "black",
          justifyContent: "center",
          alignItems: "center",
          padding: 20,
        }}
      >
        <Ionicons
          name="cloud-offline"
          size={60}
          color="#fff"
          style={{ opacity: 0.5 }}
        />
        <Text
          style={{
            color: "#fff",
            marginTop: 20,
            fontSize: 18,
            textAlign: "center",
          }}
        >
          {error || "No videos available"}
        </Text>
        <Text
          style={{
            color: "#aaa",
            marginTop: 10,
            fontSize: 14,
            textAlign: "center",
          }}
        >
          Make sure your backend is running and Vultr Object Storage is configured
        </Text>
      </View>
    );
  }

  return (
    <View style={{ flex: 1, backgroundColor: "black" }}>
      <FlatList
        pagingEnabled
        snapToInterval={Platform.OS === "android" ? height - bottomHeight : undefined}
        initialNumToRender={1}
        maxToRenderPerBatch={2}
        windowSize={3}
        removeClippedSubviews={true}
        showsVerticalScrollIndicator={false}
        onViewableItemsChanged={onViewableItemsChanged}
        data={allVideos}
        onEndReachedThreshold={0.3}
        onEndReached={fetchMoreData}
        keyExtractor={(item, index) => `video-${index}`}
        renderItem={(data) => {
          return (
            <VideoWrapper
              data={data}
              allVideos={allVideos}
              visibleIndex={visibleIndex}
              pause={pause}
              share={share}
              pauseOverride={pauseOverride}
            />
          );
        }}
      />

      {/* OTP Input Modal - shows on top of everything when email verification is required */}
      <OTPInputModal
        visible={showOTPModal}
        onCodeSubmit={(code) => {
          console.log("OTP Code submitted:", code);
          setOtpCode(code);
          setShowOTPModal(false);
          // TODO: Pass the code to the application submission flow
          // This code should be passed to the backend API when resuming the job application
        }}
        onCancel={() => {
          setShowOTPModal(false);
          setOtpCode(null);
        }}
      />
    </View>
  );
}

const $tapOverlay: ViewStyle = {
  ...StyleSheet.absoluteFillObject,
  backgroundColor: "transparent",
};

const $pauseIndicator: ViewStyle = {
  position: "absolute",
  top: "50%",
  left: "50%",
  transform: [{ translateX: -30 }, { translateY: -30 }],
  justifyContent: "center",
  alignItems: "center",
  pointerEvents: "none",
};

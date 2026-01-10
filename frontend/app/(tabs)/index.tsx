import { useBottomTabBarHeight } from "@react-navigation/bottom-tabs";

import { useEffect, useRef, useState } from "react";
import {
  Dimensions,
  FlatList,
  ListRenderItemInfo,
  Platform,
  TextStyle,
  View,
  ViewStyle,
  Text,
  Pressable,
  StyleSheet,
  Share,
} from "react-native";

import { videos, videos2, videos3 } from "../../assets/data";
import { Video, ResizeMode, AVPlaybackNativeSource } from "expo-av";
// import Video, { ResizeMode, VideoRef } from "react-native-video";
import { ReelOverlay } from "../../components/ReelOverlay";
import { Ionicons } from "@expo/vector-icons";

const { height, width } = Dimensions.get("window");

interface VideoWrapper {
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
}: VideoWrapper) => {
  const bottomHeight = useBottomTabBarHeight();
  const { index, item } = data;

  const videoRef = useRef<Video | null>(null);

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

  // Reset video to 0:00 when scrolling away from it
  useEffect(() => {
    if (visibleIndex !== index && videoRef.current) {
      // Only reset if the ref is valid
      videoRef.current.setPositionAsync(0).catch(() => {
        // Ignore errors if component is unmounted
      });
    }
  }, [visibleIndex, index]);

  return (
    <View
      style={{
        height: Platform.OS === "android" ? height - bottomHeight : height,
        width,
      }}
    >
      <Video
        ref={videoRef}
        source={{ uri: allVideos[index] }}
        style={{ height: height - bottomHeight, width }}
        resizeMode={ResizeMode.COVER}
        shouldPlay={visibleIndex === index && !pauseOverride}
        isLooping
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

  const [allVideos, setAllVideos] = useState(videos);
  const [visibleIndex, setVisibleIndex] = useState(0);
  const [pauseOverride, setPauseOverride] = useState(false);

  const numOfRefreshes = useRef(0);

  const fetchMoreData = () => {
    if (numOfRefreshes.current === 0) {
      setAllVideos([...allVideos, ...videos2]);
    }
    if (numOfRefreshes.current === 1) {
      setAllVideos([...allVideos, ...videos3]);
    }

    numOfRefreshes.current += 1;
  };

  const onViewableItemsChanged = (event: any) => {
    const newIndex = Number(event.viewableItems.at(-1).key);
    setVisibleIndex(newIndex);
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

  return (
    <View style={{ flex: 1, backgroundColor: "black" }}>
      <FlatList
        pagingEnabled
        snapToInterval={
          Platform.OS === "android" ? height - bottomHeight : undefined
        }
        initialNumToRender={1}
        showsVerticalScrollIndicator={false}
        onViewableItemsChanged={onViewableItemsChanged}
        data={allVideos}
        onEndReachedThreshold={0.3}
        onEndReached={fetchMoreData}
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



